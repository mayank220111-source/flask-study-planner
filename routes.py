from flask import Flask, request, redirect, url_for, session, make_response, render_template, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import uuid
import json
from io import BytesIO

from models import db, User, Subject, Chapter, Topic, Question, Flashcard, StudySession, Reminder, Badge, Achievement, StudyEvent
from utils import subject_stats, revision_tip, update_user_points, update_streak, grant_badge, check_achievements, get_user_achievements, update_flashcard_mastery, get_due_flashcards, export_user_data, theme_css
from flask_login import LoginManager, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.config['SECRET_KEY'] = 'key123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///study.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- Authentication Routes ----------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            return 'Username already exists!'
        
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        
        db.session.add(new_user)
        db.session.commit()
        
        # Grant welcome badge
        grant_badge(new_user, 'welcome', 'Welcome to CBSE Study Planner!')
        
        return redirect(url_for('login'))
    
    return render_template('register.html', theme_css=theme_css('light'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        else:
            return 'Invalid credentials!'
    
    return render_template('login.html', theme_css=theme_css('light'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ---------------- Theme Management ----------------

@app.route('/toggle_theme', methods=['POST'])
@login_required
def toggle_theme():
    current_user.theme = 'dark' if current_user.theme == 'light' else 'light'
    db.session.commit()
    return redirect(url_for('home'))

# ---------------- Timer Routes ----------------

@app.route('/start_timer/<int:subject_id>', methods=['POST'])
@login_required
def start_timer(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    
    if subject.user_id != current_user.id:
        return 'Unauthorized', 403
    
    # Stop any running session for this user
    running_session = StudySession.query.filter_by(
        user_id=current_user.id,
        end_time=None
    ).first()
    
    if running_session:
        running_session.end_time = datetime.utcnow()
        running_session.duration_minutes = int((running_session.end_time - running_session.start_time).total_seconds() / 60)
        db.session.commit()
    
    # Start new session
    new_session = StudySession(
        subject_id=subject_id,
        user_id=current_user.id,
        start_time=datetime.utcnow()
    )
    
    db.session.add(new_session)
    db.session.commit()
    
    # Update streak and grant points
    update_streak(current_user)
    update_user_points(current_user, 10)  # 10 points for starting a study session
    
    return redirect(url_for('subject_detail', subject_id=subject_id))

@app.route('/stop_timer/<int:subject_id>', methods=['POST'])
@login_required
def stop_timer(subject_id):
    running_session = StudySession.query.filter_by(
        user_id=current_user.id,
        subject_id=subject_id,
        end_time=None
    ).first()
    
    if running_session:
        running_session.end_time = datetime.utcnow()
        running_session.duration_minutes = int((running_session.end_time - running_session.start_time).total_seconds() / 60)
        db.session.commit()
        
        # Award additional points based on study time
        points = min(int(running_session.duration_minutes / 10) * 10, 50)  # Max 50 points
        update_user_points(current_user, points)
        
        # Check for achievements
        check_achievements(current_user)
    
    return redirect(url_for('subject_detail', subject_id=subject_id))

# ---------------- Share Routes ----------------

@app.route('/generate_share/<int:subject_id>', methods=['POST'])
@login_required
def generate_share(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    
    if subject.user_id != current_user.id:
        return 'Unauthorized', 403
    
    if not subject.share_token:
        subject.share_token = str(uuid.uuid4())
        db.session.commit()
    
    return f"Share link: {request.url_root}share/{subject.share_token}"

@app.route('/share/<token>')
def share_view(token):
    subject = Subject.query.filter_by(share_token=token).first_or_404()
    stats = subject_stats(subject.user_id)
    return render_template('share.html', subject=subject, stats=stats, theme_css=theme_css('light'))

@app.route('/share_pdf/<token>')
def share_pdf(token):
    from weasyprint import HTML
    subject = Subject.query.filter_by(share_token=token).first_or_404()
    stats = subject_stats(subject.user_id)
    
    html_string = render_template('share.html', subject=subject, stats=stats, theme_css=theme_css('light'))
    pdf = HTML(string=html_string).write_pdf()
    
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={subject.name}_study_plan.pdf'
    return response

# ---------------- Subject Routes ----------------

@app.route('/subject/<int:subject_id>', methods=['GET', 'POST'])
@login_required
def subject_detail(subject_id):
    # Use eager loading to prevent N+1 queries
    from sqlalchemy.orm import joinedload
    subject = Subject.query.options(
        joinedload(Subject.chapters).joinedload(Chapter.topics)
    ).get_or_404(subject_id)
    
    if subject.user_id != current_user.id:
        return 'Unauthorized', 403
    
    # Check if there's a running session
    running_session = StudySession.query.filter_by(
        user_id=current_user.id,
        subject_id=subject_id,
        end_time=None
    ).first()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_chapter':
            chapter_name = request.form['chapter_name']
            if chapter_name:
                new_chapter = Chapter(name=chapter_name, subject_id=subject_id)
                db.session.add(new_chapter)
                db.session.commit()
                
                # Award points for adding content
                update_user_points(current_user, 5)
        
        elif action == 'update_progress':
            topic_id = request.form.get('topic_id')
            status = request.form.get('status')
            progress = request.form.get('progress', 0)
            
            topic = Topic.query.get_or_404(topic_id)
            topic.status = status
            topic.progress = int(progress)
            
            # Update chapter last studied
            chapter = Chapter.query.get(topic.chapter_id)
            if chapter:
                chapter.last_studied = datetime.utcnow()
            
            # Award points for progress
            if status == 'completed':
                update_user_points(current_user, 25)
                update_streak(current_user)
                check_achievements(current_user)
            
            db.session.commit()
        
        return redirect(url_for('subject_detail', subject_id=subject_id))
    
    chapters = Chapter.query.filter_by(subject_id=subject_id).all()
    revision_tips = [revision_tip(chapter) for chapter in chapters]
    
    # Get due flashcards
    due_flashcards = get_due_flashcards(current_user)
    
    return render_template('subject_detail.html',
                         subject=subject,
                         chapters=chapters,
                         revision_tips=revision_tips,
                         running_session=running_session,
                         due_flashcards=due_flashcards,
                         theme_css=theme_css(current_user.theme))

@app.route('/chapter/<int:chapter_id>/add_topic', methods=['POST'])
@login_required
def add_topic(chapter_id):
    chapter = Chapter.query.get_or_404(chapter_id)
    subject = Subject.query.get(chapter.subject_id)
    
    if subject.user_id != current_user.id:
        return 'Unauthorized', 403
    
    topic_name = request.form['topic_name']
    if topic_name:
        new_topic = Topic(name=topic_name, chapter_id=chapter_id)
        db.session.add(new_topic)
        db.session.commit()
        
        # Award points
        update_user_points(current_user, 5)
    
    return redirect(url_for('subject_detail', subject_id=subject.id))

@app.route('/topic/<int:topic_id>/update', methods=['POST'])
@login_required
def update_topic(topic_id):
    topic = Topic.query.get_or_404(topic_id)
    chapter = Chapter.query.get(topic.chapter_id)
    subject = Subject.query.get(chapter.subject_id)
    
    if subject.user_id != current_user.id:
        return 'Unauthorized', 403
    
    topic.status = request.form.get('status', topic.status)
    topic.progress = int(request.form.get('progress', topic.progress))
    
    if topic.status == 'completed':
        chapter.last_studied = datetime.utcnow()
        update_user_points(current_user, 25)
        update_streak(current_user)
        check_achievements(current_user)
    
    db.session.commit()
    return redirect(url_for('subject_detail', subject_id=subject.id))

@app.route('/topic/<int:topic_id>/notes', methods=['GET', 'POST'])
@login_required
def topic_notes(topic_id):
    topic = Topic.query.get_or_404(topic_id)
    chapter = Chapter.query.get(topic.chapter_id)
    subject = Subject.query.get(chapter.subject_id)
    
    if subject.user_id != current_user.id:
        return 'Unauthorized', 403
    
    if request.method == 'POST':
        topic.notes = request.form.get('notes', '')
        db.session.commit()
        return redirect(url_for('subject_detail', subject_id=subject.id))
    
    return render_template('topic_notes.html', topic=topic, subject=subject, theme_css=theme_css(current_user.theme))

@app.route('/topic/<int:topic_id>/flashcards', methods=['GET', 'POST'])
@login_required
def topic_flashcards(topic_id):
    topic = Topic.query.get_or_404(topic_id)
    chapter = Chapter.query.get(topic.chapter_id)
    subject = Subject.query.get(chapter.subject_id)
    
    if subject.user_id != current_user.id:
        return 'Unauthorized', 403
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_flashcard':
            front = request.form.get('front')
            back = request.form.get('back')
            if front and back:
                new_flashcard = Flashcard(
                    topic_id=topic_id,
                    front=front,
                    back=back,
                    next_review=datetime.utcnow()
                )
                db.session.add(new_flashcard)
                db.session.commit()
                
                # Award points for creating flashcards
                update_user_points(current_user, 3)
        
        elif action == 'review_flashcard':
            flashcard_id = request.form.get('flashcard_id')
            correct = request.form.get('correct') == 'true'
            
            flashcard = Flashcard.query.get_or_404(flashcard_id)
            update_flashcard_mastery(flashcard, correct)
            
            # Award points for reviewing
            update_user_points(current_user, 2 if correct else 1)
            check_achievements(current_user)
        
        return redirect(url_for('topic_flashcards', topic_id=topic_id))
    
    flashcards = Flashcard.query.filter_by(topic_id=topic_id).all()
    return render_template('topic_flashcards.html', topic=topic, subject=subject, flashcards=flashcards, theme_css=theme_css(current_user.theme))

@app.route('/chapter/<int:chapter_id>/add_question', methods=['POST'])
@login_required
def add_question(chapter_id):
    chapter = Chapter.query.get_or_404(chapter_id)
    subject = Subject.query.get(chapter.subject_id)
    
    if subject.user_id != current_user.id:
        return 'Unauthorized', 403
    
    question_text = request.form.get('question_text')
    difficulty = request.form.get('difficulty', 'medium')
    
    if question_text:
        new_question = Question(
            chapter_id=chapter_id,
            text=question_text,
            difficulty=difficulty
        )
        db.session.add(new_question)
        db.session.commit()
        
        # Award points
        update_user_points(current_user, 2)
    
    return redirect(url_for('subject_detail', subject_id=subject.id))

# ---------------- Dashboard Routes ----------------

@app.route('/add_subject', methods=['POST'])
@login_required
def add_subject():
    subject_name = request.form['subject_name']
    color = request.form.get('color', '#3498db')
    
    if subject_name:
        new_subject = Subject(
            name=subject_name,
            user_id=current_user.id,
            color=color
        )
        db.session.add(new_subject)
        db.session.commit()
        
        # Award points for adding a subject
        update_user_points(current_user, 10)
    
    return redirect(url_for('home'))

@app.route('/')
@login_required
def home():
    stats = subject_stats(current_user.id)
    achievements = get_user_achievements(current_user)
    
    # Get upcoming reminders
    upcoming_reminders = Reminder.query.filter_by(
        user_id=current_user.id,
        is_completed=False
    ).filter(
        Reminder.reminder_time >= datetime.utcnow()
    ).order_by(Reminder.reminder_time).limit(5).all()
    
    # Get due flashcards
    due_flashcards = get_due_flashcards(current_user)
    
    # Get recent study sessions
    recent_sessions = StudySession.query.filter_by(
        user_id=current_user.id
    ).order_by(StudySession.start_time.desc()).limit(5).all()
    
    return render_template('index.html',
                         stats=stats,
                         achievements=achievements,
                         upcoming_reminders=upcoming_reminders,
                         due_flashcards=due_flashcards,
                         recent_sessions=recent_sessions,
                         theme_css=theme_css(current_user.theme))

# ---------------- Gamification Routes ----------------

@app.route('/achievements')
@login_required
def achievements():
    achievements = get_user_achievements(current_user)
    return render_template('achievements.html', achievements=achievements, theme_css=theme_css(current_user.theme))

@app.route('/leaderboard')
@login_required
def leaderboard():
    users = User.query.order_by(User.points.desc()).limit(10).all()
    return render_template('leaderboard.html', users=users, theme_css=theme_css(current_user.theme))

# ---------------- Reminder Routes ----------------

@app.route('/reminders', methods=['GET', 'POST'])
@login_required
def reminders():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_reminder':
            title = request.form['title']
            description = request.form.get('description', '')
            reminder_time = datetime.strptime(request.form['reminder_time'], '%Y-%m-%dT%H:%M')
            repeat = request.form.get('repeat', 'once')
            subject_id = request.form.get('subject_id')
            
            new_reminder = Reminder(
                user_id=current_user.id,
                subject_id=int(subject_id) if subject_id else None,
                title=title,
                description=description,
                reminder_time=reminder_time,
                repeat=repeat
            )
            db.session.add(new_reminder)
            db.session.commit()
            
            # Award points
            update_user_points(current_user, 5)
        
        elif action == 'complete_reminder':
            reminder_id = request.form.get('reminder_id')
            reminder = Reminder.query.get_or_404(reminder_id)
            
            if reminder.user_id != current_user.id:
                return 'Unauthorized', 403
            
            reminder.is_completed = True
            
            # If recurring, create next reminder
            if reminder.repeat != 'once':
                next_time = reminder.reminder_time
                if reminder.repeat == 'daily':
                    next_time += timedelta(days=1)
                elif reminder.repeat == 'weekly':
                    next_time += timedelta(weeks=1)
                elif reminder.repeat == 'monthly':
                    next_time += timedelta(days=30)
                
                new_reminder = Reminder(
                    user_id=current_user.id,
                    subject_id=reminder.subject_id,
                    title=reminder.title,
                    description=reminder.description,
                    reminder_time=next_time,
                    repeat=reminder.repeat
                )
                db.session.add(new_reminder)
            
            db.session.commit()
            update_user_points(current_user, 10)
        
        return redirect(url_for('reminders'))
    
    reminders = Reminder.query.filter_by(user_id=current_user.id).order_by(Reminder.reminder_time).all()
    subjects = Subject.query.filter_by(user_id=current_user.id).all()
    
    return render_template('reminders.html', reminders=reminders, subjects=subjects, theme_css=theme_css(current_user.theme))

@app.route('/reminder/<int:reminder_id>/delete', methods=['POST'])
@login_required
def delete_reminder(reminder_id):
    reminder = Reminder.query.get_or_404(reminder_id)
    
    if reminder.user_id != current_user.id:
        return 'Unauthorized', 403
    
    db.session.delete(reminder)
    db.session.commit()
    
    return redirect(url_for('reminders'))

# ---------------- Calendar/Study Events Routes ----------------

@app.route('/calendar', methods=['GET', 'POST'])
@login_required
def calendar():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_event':
            title = request.form['title']
            description = request.form.get('description', '')
            event_date = datetime.strptime(request.form['event_date'], '%Y-%m-%d').date()
            start_time = datetime.strptime(request.form['start_time'], '%H:%M').time() if request.form.get('start_time') else None
            end_time = datetime.strptime(request.form['end_time'], '%H:%M').time() if request.form.get('end_time') else None
            event_type = request.form.get('event_type', 'study')
            subject_id = request.form.get('subject_id')
            
            new_event = StudyEvent(
                user_id=current_user.id,
                subject_id=int(subject_id) if subject_id else None,
                title=title,
                description=description,
                event_date=event_date,
                start_time=start_time,
                end_time=end_time,
                event_type=event_type
            )
            db.session.add(new_event)
            db.session.commit()
            
            # Award points
            update_user_points(current_user, 5)
        
        elif action == 'delete_event':
            event_id = request.form.get('event_id')
            event = StudyEvent.query.get_or_404(event_id)
            
            if event.user_id != current_user.id:
                return 'Unauthorized', 403
            
            db.session.delete(event)
            db.session.commit()
        
        return redirect(url_for('calendar'))
    
    # Get events for the current month
    today = datetime.now()
    start_of_month = today.replace(day=1)
    if today.month == 12:
        end_of_month = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end_of_month = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    
    events = StudyEvent.query.filter_by(user_id=current_user.id).filter(
        StudyEvent.event_date >= start_of_month,
        StudyEvent.event_date <= end_of_month
    ).order_by(StudyEvent.event_date, StudyEvent.start_time).all()
    
    subjects = Subject.query.filter_by(user_id=current_user.id).all()
    
    return render_template('calendar.html', events=events, subjects=subjects, theme_css=theme_css(current_user.theme))

# ---------------- Statistics Routes ----------------

@app.route('/statistics')
@login_required
def statistics():
    # Get detailed statistics
    stats = subject_stats(current_user.id)
    achievements = get_user_achievements(current_user)
    
    # Study time by day for the last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    daily_study_time = {}
    
    sessions = StudySession.query.filter_by(user_id=current_user.id).filter(
        StudySession.start_time >= thirty_days_ago
    ).all()
    
    for session in sessions:
        date = session.start_time.date()
        daily_study_time[date] = daily_study_time.get(date, 0) + session.duration_minutes
    
    # Subject-wise study time
    subject_study_time = {}
    for subject in current_user.subjects:
        total_time = sum(s.duration_minutes for s in subject.study_sessions)
        subject_study_time[subject.name] = total_time
    
    # Topic completion rate
    total_topics = sum(len(ch.topics) for ch in Chapter.query.join(Subject).filter_by(user_id=current_user.id).all())
    completed_topics = Topic.query.filter_by(status='completed').join(Chapter).join(Subject).filter_by(user_id=current_user.id).count()
    completion_rate = (completed_topics / total_topics * 100) if total_topics > 0 else 0
    
    # Flashcard mastery distribution
    flashcard_mastery = {
        'beginner': 0,
        'intermediate': 0,
        'advanced': 0,
        'master': 0
    }
    
    flashcards = Flashcard.query.join(Topic).join(Chapter).join(Subject).filter_by(user_id=current_user.id).all()
    for fc in flashcards:
        if fc.mastery_level <= 1:
            flashcard_mastery['beginner'] += 1
        elif fc.mastery_level <= 3:
            flashcard_mastery['intermediate'] += 1
        elif fc.mastery_level <= 4:
            flashcard_mastery['advanced'] += 1
        else:
            flashcard_mastery['master'] += 1
    
    return render_template('statistics.html',
                         stats=stats,
                         achievements=achievements,
                         daily_study_time=daily_study_time,
                         subject_study_time=subject_study_time,
                         completion_rate=completion_rate,
                         flashcard_mastery=flashcard_mastery,
                         theme_css=theme_css(current_user.theme))

# ---------------- Export/Import Routes ----------------

@app.route('/export')
@login_required
def export_data():
    data = export_user_data(current_user)
    response = make_response(data)
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = 'attachment; filename=study_planner_export.json'
    return response

@app.route('/import', methods=['POST'])
@login_required
def import_data():
    if 'file' not in request.files:
        return 'No file uploaded', 400
    
    file = request.files['file']
    if file.filename == '':
        return 'No file selected', 400
    
    try:
        data = json.loads(file.read().decode('utf-8'))
        
        # Import subjects and their content
        for subject_data in data.get('subjects', []):
            new_subject = Subject(
                user_id=current_user.id,
                name=subject_data['name'],
                color=subject_data.get('color', '#3498db')
            )
            db.session.add(new_subject)
            db.session.flush()  # Get the ID
            
            for chapter_data in subject_data.get('chapters', []):
                new_chapter = Chapter(
                    subject_id=new_subject.id,
                    name=chapter_data['name']
                )
                db.session.add(new_chapter)
                db.session.flush()
                
                for topic_data in chapter_data.get('topics', []):
                    new_topic = Topic(
                        chapter_id=new_chapter.id,
                        name=topic_data['name'],
                        status=topic_data.get('status', 'not_started'),
                        progress=topic_data.get('progress', 0),
                        notes=topic_data.get('notes', '')
                    )
                    db.session.add(new_topic)
                    db.session.flush()
                    
                    for flashcard_data in topic_data.get('flashcards', []):
                        new_flashcard = Flashcard(
                            topic_id=new_topic.id,
                            front=flashcard_data['front'],
                            back=flashcard_data['back'],
                            mastery_level=flashcard_data.get('mastery_level', 0),
                            next_review=datetime.utcnow()
                        )
                        db.session.add(new_flashcard)
        
        # Import reminders
        for reminder_data in data.get('reminders', []):
            new_reminder = Reminder(
                user_id=current_user.id,
                title=reminder_data['title'],
                description=reminder_data.get('description', ''),
                reminder_time=datetime.fromisoformat(reminder_data['reminder_time']),
                repeat=reminder_data.get('repeat', 'once')
            )
            db.session.add(new_reminder)
        
        db.session.commit()
        
        # Award points for importing
        update_user_points(current_user, 50)
        
        return redirect(url_for('home'))
    
    except Exception as e:
        db.session.rollback()
        return f'Error importing data: {str(e)}', 400

# Create all tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)