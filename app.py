from flask import Flask, request, redirect, url_for, session, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'key123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///study.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ---------------- Models ----------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(100))
    theme = db.Column(db.String(10), default='light')  # 'light' or 'dark'

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    share_token = db.Column(db.String(64), unique=True, nullable=True)  # for read-only share

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    last_studied = db.Column(db.DateTime, nullable=True)  # for revision schedule

class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    status = db.Column(db.String(20), default='not_started')  # not_started, in_progress, completed
    progress = db.Column(db.Integer, default=0)               # 0–100
    notes = db.Column(db.Text, default='')

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    text = db.Column(db.Text)

class Flashcard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'))
    front = db.Column(db.Text)  # question/formula name
    back = db.Column(db.Text)   # answer/formula

class StudySession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)  # null while running

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- Theme helpers ----------------
def theme_css(theme):
    if theme == 'dark':
        return {
            'body_bg': '#1f1f1f',
            'text': '#eaeaea',
            'card_bg': '#2a2a2a',
            'border': '#444',
            'subject_bg': '#3a3a3a',
            'subject_hover': '#333',
            'link': '#66b2ff',
            'accent': '#3498db',
            'button_bg': '#27ae60',
            'button_hover': '#229954',
            'danger_bg': '#e74c3c',
            'danger_hover': '#c0392b'
        }
    return {
        'body_bg': '#f5f5f5',
        'text': '#2c3e50',
        'card_bg': '#ffffff',
        'border': '#3498db',
        'subject_bg': '#3498db',
        'subject_hover': '#2980b9',
        'link': '#008CBA',
        'accent': '#3498db',
        'button_bg': '#27ae60',
        'button_hover': '#229954',
        'danger_bg': '#e74c3c',
        'danger_hover': '#c0392b'
    }

# ---------------- Utility: stats & revision ----------------
def subject_stats(user_id):
    subjects = Subject.query.filter_by(user_id=user_id).all()
    chapters = Chapter.query.join(Subject, Chapter.subject_id == Subject.id).filter(Subject.user_id == user_id).all()
    topics = Topic.query.join(Chapter, Topic.chapter_id == Chapter.id).join(Subject, Chapter.subject_id == Subject.id).filter(Subject.user_id == user_id).all()
    total_chapters = len(chapters)
    total_topics = len(topics)
    completed = sum(1 for t in topics if t.status == 'completed')
    in_progress = sum(1 for t in topics if t.status == 'in_progress')
    # Study hours
    sessions = StudySession.query.filter_by(user_id=user_id).all()
    minutes = 0
    for s in sessions:
        if s.end_time:
            minutes += int((s.end_time - s.start_time).total_seconds() // 60)
    return {
        'subjects': len(subjects),
        'chapters': total_chapters,
        'topics': total_topics,
        'completed': completed,
        'in_progress': in_progress,
        'minutes': minutes
    }

def revision_tip(chapter: Chapter):
    if chapter.last_studied:
        next_rev = chapter.last_studied + timedelta(days=7)
        return f"You studied on {chapter.last_studied.strftime('%b %d')}. Revise on {next_rev.strftime('%b %d')} (7-day rule)."
    return "No study date yet. Update any topic to set last studied."

# ---------------- Auth Routes ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['username']).first():
            return '<h2>User exists</h2><a href="/register">Back</a>'
        user = User(username=request.form['username'],
                    password=generate_password_hash(request.form['password']))
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return '''
    <style>
        body { font-family: Arial; margin: 40px; background: #f0f0f0; }
        h2 { color: #333; }
        input { padding: 8px; margin: 5px 0; width: 220px; }
        button { padding: 8px 15px; background: #4CAF50; color: white; border: none; cursor: pointer; }
        a { color: #008CBA; text-decoration: none; }
    </style>
    <h2>Register</h2>
    <form method="post">
        Username: <input name="username" required><br>
        Password: <input type="password" name="password" required><br>
        <button>Register</button>
    </form>
    <a href="/login">Have account? Login</a>
    '''

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('home'))
        return '<h2>Wrong info</h2><a href="/login">Back</a>'
    return '''
    <style>
        body { font-family: Arial; margin: 40px; background: #f0f0f0; }
        h2 { color: #333; }
        input { padding: 8px; margin: 5px 0; width: 220px; }
        button { padding: 8px 15px; background: #008CBA; color: white; border: none; cursor: pointer; }
        a { color: #008CBA; text-decoration: none; }
    </style>
    <h2>Login</h2>
    <form method="post">
        Username: <input name="username" required><br>
        Password: <input type="password" name="password" required><br>
        <button>Login</button>
    </form>
    <a href="/register">Register</a>
    '''

# ---------------- Theme toggle ----------------
@app.route('/toggle_theme', methods=['POST'])
@login_required
def toggle_theme():
    current_user.theme = 'dark' if current_user.theme == 'light' else 'light'
    db.session.commit()
    return redirect(url_for('home'))

# ---------------- Timer: start/stop ----------------
@app.route('/start_timer/<int:subject_id>', methods=['POST'])
@login_required
def start_timer(subject_id):
    subject = Subject.query.get(subject_id)
    if not subject or subject.user_id != current_user.id:
        return 'Not authorized', 403
    # If already running, ignore
    running = StudySession.query.filter_by(user_id=current_user.id, subject_id=subject_id, end_time=None).first()
    if not running:
        sess = StudySession(subject_id=subject_id, user_id=current_user.id, start_time=datetime.now())
        db.session.add(sess)
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/stop_timer/<int:subject_id>', methods=['POST'])
@login_required
def stop_timer(subject_id):
    subject = Subject.query.get(subject_id)
    if not subject or subject.user_id != current_user.id:
        return 'Not authorized', 403
    running = StudySession.query.filter_by(user_id=current_user.id, subject_id=subject_id, end_time=None).first()
    if running:
        running.end_time = datetime.now()
        db.session.commit()
    return redirect(url_for('home'))

# ---------------- Share: generate token & read-only view ----------------
@app.route('/generate_share/<int:subject_id>', methods=['POST'])
@login_required
def generate_share(subject_id):
    subject = Subject.query.get(subject_id)
    if not subject or subject.user_id != current_user.id:
        return 'Not authorized', 403
    subject.share_token = uuid.uuid4().hex
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/share/<token>')
def share_view(token):
    subject = Subject.query.filter_by(share_token=token).first()
    if not subject:
        return 'Invalid link', 404
    chapters = Chapter.query.filter_by(subject_id=subject.id).all()
    css = theme_css('light')
    html = f'''
    <style>
        body {{ font-family: Arial; margin: 20px; background: {css['body_bg']}; color: {css['text']}; }}
        h1 {{ color: {css['text']}; }}
        .card {{ background: {css['card_bg']}; padding: 15px; margin: 10px 0; border: 2px solid {css['accent']}; border-radius: 5px; }}
        ul {{ background: {css['card_bg']}; padding: 15px; border-radius: 5px; }}
        li {{ padding: 6px; }}
    </style>
    <h1>📤 Shared Study Plan (Read-only): {subject.name}</h1>
    <div class="card">
        <p>This is a read-only view. Use your own app to edit.</p>
    </div>
    <h3>Chapters & Topics</h3>
    <ul>
    '''
    for ch in chapters:
        html += f'<li><strong>{ch.name}</strong><ul>'
        topics = Topic.query.filter_by(chapter_id=ch.id).all()
        for t in topics:
            icon = '🔴' if t.status == 'not_started' else ('🟡' if t.status == 'in_progress' else '🟢')
            html += f'<li>{t.name} — {icon} {t.status.replace("_"," ").title()} ({t.progress}% understood)</li>'
        html += '</ul></li>'
    html += '</ul>'
    return html

@app.route('/share_pdf/<token>')
def share_pdf(token):
    subject = Subject.query.filter_by(share_token=token).first()
    if not subject:
        return 'Invalid link', 404
    chapters = Chapter.query.filter_by(subject_id=subject.id).all()
    # Simple HTML -> PDF via browser print dialog (Content-Type hints)
    html = f'''
    <h1>Study Plan: {subject.name}</h1>
    <hr>
    '''
    for ch in chapters:
        html += f'<h2>Chapter: {ch.name}</h2><ul>'
        topics = Topic.query.filter_by(chapter_id=ch.id).all()
        for t in topics:
            html += f'<li>{t.name} — {t.status} — {t.progress}%</li>'
        html += '</ul>'
    resp = make_response(html)
    resp.headers['Content-Type'] = 'text/html'
    # Users can Ctrl+P -> Save as PDF
    return resp

# ---------------- Subject Detail ----------------
@app.route('/subject/<int:subject_id>', methods=['GET', 'POST'])
@login_required
def subject_detail(subject_id):
    subject = Subject.query.get(subject_id)
    if not subject or subject.user_id != current_user.id:
        return 'Not found', 404

    if request.method == 'POST':
        chapter_name = request.form['chapter_name']
        if chapter_name:
            chapter = Chapter(name=chapter_name, subject_id=subject_id, last_studied=None)
            db.session.add(chapter)
            db.session.commit()
        return redirect(url_for('subject_detail', subject_id=subject_id))

    chapters = Chapter.query.filter_by(subject_id=subject_id).all()
    filter_status = request.args.get('status')

    css = theme_css(current_user.theme)
    html = f'''
    <style>
        body {{ font-family: Arial; margin: 20px; background: {css['body_bg']}; color: {css['text']}; }}
        h2 {{ color: {css['text']}; }}
        .form {{ background: {css['card_bg']}; padding: 15px; margin: 15px 0; border: 2px solid {css['border']}; border-radius: 5px; }}
        input, button, select, textarea {{ padding: 8px; margin: 5px; }}
        button {{ background: {css['button_bg']}; color: white; border: none; cursor: pointer; border-radius: 3px; }}
        button:hover {{ background: {css['button_hover']}; }}
        ul {{ background: {css['card_bg']}; padding: 15px; border-radius: 5px; }}
        li {{ padding: 8px; margin: 5px 0; }}
        a {{ color: {css['link']}; text-decoration: none; }}
        .summary {{ margin-top: 8px; color: {css['text']}; }}
        .tip {{ color: orange; margin-top: 4px; }}
        .filters {{ margin: 10px 0; }}
        .filters a {{ margin-right: 8px; }}
        .topbar {{ display:flex; justify-content: space-between; align-items:center; }}
        .toggle {{ background: {css['subject_bg']}; color: white; border:none; padding:6px 10px; border-radius:4px; cursor:pointer; }}
        .toggle:hover {{ background: {css['subject_hover']}; }}
        .questions {{ background: {css['card_bg']}; border: 2px solid {css['border']}; border-radius: 5px; padding: 12px; margin-top: 10px; }}
        .q-item {{ background: #f9f9f9; color:#333; border: 1px solid #ddd; border-radius: 4px; padding: 8px; margin: 6px 0; }}
        .rev {{ background: {css['card_bg']}; border: 2px solid {css['border']}; border-radius: 5px; padding: 12px; margin-top: 10px; }}
    </style>
    <div class="topbar">
        <h2>{subject.name}</h2>
        <div>
            <form method="post" action="/toggle_theme" style="display:inline;">
                <button class="toggle" type="submit">Toggle: {current_user.theme.title()} Mode</button>
            </form>
            <form method="post" action="/generate_share/{subject_id}" style="display:inline;margin-left:8px;">
                <button class="toggle" type="submit">Generate Share Link</button>
            </form>
        </div>
    </div>
    <div class="form">
        <h3>Add Chapter</h3>
        <form method="post">
            Chapter Name: <input name="chapter_name" placeholder="Ch1 Kinetics...">
            <button type="submit">Add Chapter</button>
        </form>
    </div>
    <div class="filters">
        <strong>Quick filter:</strong>
        <a href="/subject/{subject_id}">All</a>
        <a href="/subject/{subject_id}?status=not_started">🔴 Not Started</a>
        <a href="/subject/{subject_id}?status=in_progress">🟡 In Progress</a>
        <a href="/subject/{subject_id}?status=completed">🟢 Completed</a>
    </div>
    <h3>Chapters</h3>
    <ul>
    '''
    for ch in chapters:
        topics = Topic.query.filter_by(chapter_id=ch.id).all()
        if filter_status:
            topics = [t for t in topics if t.status == filter_status]
        html += f'''
        <li><strong>{ch.name}</strong>
            <div class="rev"><em>Revision:</em> {revision_tip(ch)}</div>
            <form method="post" action="/chapter/{ch.id}/add_topic">
                <input name="topic_name" placeholder="New topic..." required>
                <select name="status">
                    <option value="not_started">🔴 Not Started</option>
                    <option value="in_progress">🟡 In Progress</option>
                    <option value="completed">🟢 Completed</option>
                </select>
                <input type="number" name="progress" min="0" max="100" value="0">
                <button type="submit">Add Topic</button>
            </form>
            <ul>
        '''
        total_progress, count, completed = 0, 0, 0
        for t in topics:
            icon = '🔴' if t.status == 'not_started' else ('🟡' if t.status == 'in_progress' else '🟢')
            status_text = t.status.replace('_', ' ').title()
            note_icon = ' 📌' if t.notes else ''
            html += f'''
                <li>{t.name}{note_icon} - {icon} {status_text} ({t.progress}% understood)
                    <form method="post" action="/topic/{t.id}/update">
                        <select name="status">
                            <option value="not_started" {'selected' if t.status=='not_started' else ''}>🔴 Not Started</option>
                            <option value="in_progress" {'selected' if t.status=='in_progress' else ''}>🟡 In Progress</option>
                            <option value="completed" {'selected' if t.status=='completed' else ''}>🟢 Completed</option>
                        </select>
                        <input type="number" name="progress" min="0" max="100" value="{t.progress}">
                        <button type="submit">Update</button>
                    </form>
                    <a href="/topic/{t.id}/notes">📝 Notes</a>
                    <a href="/topic/{t.id}/flashcards" style="margin-left:10px;">🔢 Flashcards</a>
                </li>
            '''
            if t.status == 'completed' and t.progress < 100:
                html += "<div class='tip'>Tip: Completed topics usually have 100% progress!</div>"
            total_progress += t.progress
            count += 1
            if t.status == 'completed':
                completed += 1
        avg = round(total_progress / count, 1) if count else 0
        html += f'''
            </ul>
            <div class="summary"><em>Summary: {count} topics, {completed} completed, avg. {avg}%</em></div>
            <div class="questions">
                <h4>Important Questions</h4>
                <form method="post" action="/chapter/{ch.id}/add_question">
                    <input name="question_text" placeholder="Add important question..." style="width:70%;" required>
                    <button type="submit">Add</button>
                </form>
        '''
        questions = Question.query.filter_by(chapter_id=ch.id).all()
        if not questions:
            html += "<div class='q-item'>No questions yet. Add common exam questions above.</div>"
        else:
            for q in questions:
                html += f"<div class='q-item'>Q: {q.text}</div>"
        html += "</div></li>"
    html += '''
    </ul>
    <a href="/">Back to Subjects</a>
    '''
    return html

# ---------------- Add Topic ----------------
@app.route('/chapter/<int:chapter_id>/add_topic', methods=['POST'])
@login_required
def add_topic(chapter_id):
    chapter = Chapter.query.get(chapter_id)
    if not chapter:
        return 'Chapter not found', 404
    topic_name = request.form['topic_name']
    status = request.form.get('status', 'not_started')
    try:
        progress = int(request.form.get('progress', 0))
    except ValueError:
        progress = 0
    progress = max(0, min(progress, 100))
    if topic_name:
        topic = Topic(name=topic_name, chapter_id=chapter_id, status=status, progress=progress)
        db.session.add(topic)
        # Set last studied when adding a topic
        chapter.last_studied = datetime.now()
        db.session.commit()
    return redirect(url_for('subject_detail', subject_id=chapter.subject_id))

# ---------------- Update Topic ----------------
@app.route('/topic/<int:topic_id>/update', methods=['POST'])
@login_required
def update_topic(topic_id):
    topic = Topic.query.get(topic_id)
    if not topic:
        return 'Topic not found', 404
    topic.status = request.form.get('status', topic.status)
    try:
        topic.progress = int(request.form.get('progress', topic.progress))
    except ValueError:
        pass
    topic.progress = max(0, min(topic.progress, 100))
    # Update chapter last studied on any topic change
    chapter = Chapter.query.get(topic.chapter_id)
    if chapter:
        chapter.last_studied = datetime.now()
    db.session.commit()
    return redirect(url_for('subject_detail', subject_id=chapter.subject_id))

# ---------------- Topic Notes ----------------
@app.route('/topic/<int:topic_id>/notes', methods=['GET', 'POST'])
@login_required
def topic_notes(topic_id):
    topic = Topic.query.get(topic_id)
    if not topic:
        return 'Topic not found', 404
    chapter = Chapter.query.get(topic.chapter_id)
    subject = Subject.query.get(chapter.subject_id) if chapter else None
    if not subject or subject.user_id != current_user.id:
        return 'Not authorized', 403

    if request.method == 'POST':
        topic.notes = request.form.get('notes', '')
        # notes also count as study activity
        chapter.last_studied = datetime.now()
        db.session.commit()
        return redirect(url_for('subject_detail', subject_id=subject.id))

    css = theme_css(current_user.theme)
    return f'''
    <style>
        body {{ font-family: Arial; margin: 20px; background: {css['body_bg']}; color: {css['text']}; }}
        h2 {{ color: {css['text']}; }}
        .form {{ background: {css['card_bg']}; padding: 15px; margin: 15px 0; border: 2px solid {css['border']}; border-radius: 5px; }}
        textarea {{ width: 100%; height: 220px; padding: 8px; }}
        button {{ background: {css['button_bg']}; color: white; border: none; cursor: pointer; border-radius: 3px; padding: 8px 15px; }}
        a {{ color: {css['link']}; text-decoration: none; }}
    </style>
    <h2>Notes for: {topic.name}</h2>
    <div class="form">
        <form method="post">
            <textarea name="notes" placeholder="- Rate = change in conc/time&#10;- Units: mol/L/s&#10;- Formula: v = -d[A]/dt">{topic.notes or ''}</textarea><br>
            <button type="submit">Save Notes</button>
        </form>
    </div>
    <a href="/subject/{subject.id}">Back to Chapters</a>
    '''

# ---------------- Flashcards ----------------
@app.route('/topic/<int:topic_id>/flashcards', methods=['GET', 'POST'])
@login_required
def topic_flashcards(topic_id):
    topic = Topic.query.get(topic_id)
    if not topic:
        return 'Topic not found', 404
    chapter = Chapter.query.get(topic.chapter_id)
    subject = Subject.query.get(chapter.subject_id) if chapter else None
    if not subject or subject.user_id != current_user.id:
        return 'Not authorized', 403

    if request.method == 'POST':
        front = request.form.get('front', '').strip()
        back = request.form.get('back', '').strip()
        if front and back:
            fc = Flashcard(topic_id=topic_id, front=front, back=back)
            db.session.add(fc)
            # flashcard creation counts as study activity
            chapter.last_studied = datetime.now()
            db.session.commit()
        return redirect(url_for('topic_flashcards', topic_id=topic_id))

    cards = Flashcard.query.filter_by(topic_id=topic_id).all()
    css = theme_css(current_user.theme)
    html = f'''
    <style>
        body {{ font-family: Arial; margin: 20px; background: {css['body_bg']}; color: {css['text']}; }}
        h2 {{ color: {css['text']}; }}
        .form {{ background: {css['card_bg']}; padding: 15px; margin: 15px 0; border: 2px solid {css['border']}; border-radius: 5px; }}
        input, textarea, button {{ padding: 8px; margin: 5px; }}
        button {{ background: {css['button_bg']}; color: white; border: none; cursor: pointer; border-radius: 3px; padding: 8px 15px; }}
        a {{ color: {css['link']}; text-decoration: none; }}
        .flashcards {{ background: {css['card_bg']}; border: 2px solid {css['border']}; border-radius: 5px; padding: 12px; margin-top: 10px; }}
        .fc-item {{ background: #f9f9f9; color:#333; border: 1px solid #ddd; border-radius: 4px; padding: 8px; margin: 6px 0; }}
        .fc-front {{ font-weight: bold; }}
    </style>
    <h2>Flashcards for: {topic.name}</h2>
    <div class="form">
        <h3>Create Flashcard</h3>
        <form method="post">
            <input name="front" placeholder="Front: e.g., Arrhenius Equation" required><br>
            <textarea name="back" placeholder="Back: e.g., k = A·e^(-Ea/RT)" required></textarea><br>
            <button type="submit">Add Flashcard</button>
        </form>
    </div>
    <div class="flashcards">
        <h3>Study Flashcards</h3>
    '''
    if not cards:
        html += '<div class="fc-item">No flashcards yet. Add some above.</div>'
    else:
        for c in cards:
            html += f'<div class="fc-item"><div class="fc-front">Front: {c.front}</div><div class="fc-back">Back: {c.back}</div></div>'
    html += f'</div><br><a href="/subject/{subject.id}">Back to Chapters</a>'
    return html

# ---------------- Add Question ----------------
@app.route('/chapter/<int:chapter_id>/add_question', methods=['POST'])
@login_required
def add_question(chapter_id):
    chapter = Chapter.query.get(chapter_id)
    if not chapter:
        return 'Chapter not found', 404
    subject = Subject.query.get(chapter.subject_id)
    if not subject or subject.user_id != current_user.id:
        return 'Not authorized', 403
    text = request.form.get('question_text', '').strip()
    if text:
        q = Question(chapter_id=chapter_id, text=text)
        db.session.add(q)
        # adding question counts as study activity
        chapter.last_studied = datetime.now()
        db.session.commit()
    return redirect(url_for('subject_detail', subject_id=subject.id))

# ---------------- Add Subject ----------------
@app.route('/add_subject', methods=['POST'])
@login_required
def add_subject():
    name = request.form['subject_name']
    if name:
        subject = Subject(name=name, user_id=current_user.id)
        db.session.add(subject)
        db.session.commit()
    return redirect(url_for('home'))

# ---------------- Home + Quick Stats ----------------
@app.route('/')
@login_required
def home():
    subjects = Subject.query.filter_by(user_id=current_user.id).all()
    css = theme_css(current_user.theme)
    stats = subject_stats(current_user.id)
    html = f'''
    <style>
        body {{ font-family: Arial; margin: 20px; background: {css['body_bg']}; color: {css['text']}; }}
        h1 {{ color: {css['text']}; text-align: center; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .subject {{ background: {css['subject_bg']}; color: white; padding: 15px; margin: 10px 0; border-radius: 5px; cursor: pointer; }}
        .subject:hover {{ background: {css['subject_hover']}; }}
        .subject a {{ color: white; text-decoration: none; display: block; }}
        .subject-form {{ background: {css['card_bg']}; padding: 15px; margin: 20px 0; border: 2px solid {css['accent']}; border-radius: 5px; }}
        input, button {{ padding: 8px; margin: 5px; }}
        button {{ background: {css['button_bg']}; color: white; border: none; cursor: pointer; border-radius: 3px; }}
        button:hover {{ background: {css['button_hover']}; }}
        .logout {{ background: {css['danger_bg']}; color: white; padding: 8px 15px; border: none; border-radius: 3px; cursor: pointer; }}
        .logout:hover {{ background: {css['danger_hover']}; }}
        .topbar {{ display:flex; justify-content: space-between; align-items:center; }}
        .toggle {{ background: {css['subject_bg']}; color: white; border:none; padding:6px 10px; border-radius:4px; cursor:pointer; }}
        .toggle:hover {{ background: {css['subject_hover']}; }}
        .stats {{ background: {css['card_bg']}; padding: 15px; border: 2px solid {css['accent']}; border-radius: 5px; margin-top: 10px; }}
        .share {{ font-size: 0.9em; margin-top: 6px; }}
        .timer {{ margin-top: 6px; }}
    </style>
    <div class="container">
        <div class="topbar">
            <h1>📚 CBSE Study Planner - {current_user.username}</h1>
            <form method="post" action="/toggle_theme">
                <button class="toggle" type="submit">Toggle: {current_user.theme.title()} Mode</button>
            </form>
        </div>
        <div class="subject-form">
            <h3>Add Subject</h3>
            <form method="post" action="/add_subject">
                Subject Name: <input name="subject_name" placeholder="Physics, Chemistry, Maths..." required>
                <button type="submit">Add Subject</button>
            </form>
        </div>
        <div class="stats">
            <h3>📊 Quick Stats</h3>
            <div>📚 Total Chapters: {stats['chapters']}</div>
            <div>✅ Completed Topics: {stats['completed']}</div>
            <div>⏳ In Progress Topics: {stats['in_progress']}</div>
            <div>📘 Total Topics: {stats['topics']}</div>
            <div>⏱️ Study Hours: {stats['minutes'] // 60} hrs {stats['minutes'] % 60} min</div>
        </div>
        <h2>Your Subjects</h2>
    '''
    for subject in subjects:
        share_info = f"Share Link: /share/{subject.share_token} | PDF: /share_pdf/{subject.share_token}" if subject.share_token else "No share link yet."
        # Timer controls
        running = StudySession.query.filter_by(user_id=current_user.id, subject_id=subject.id, end_time=None).first()
        timer_controls = f'''
            <div class="timer">
                <form method="post" action="/start_timer/{subject.id}" style="display:inline;">
                    <button type="submit">▶ Start Timer</button>
                </form>
                <form method="post" action="/stop_timer/{subject.id}" style="display:inline;margin-left:6px;">
                    <button type="submit">⏹ Stop Timer</button>
                </form>
                <span style="margin-left:8px;">Status: {'Running' if running else 'Stopped'}</span>
            </div>
        '''
        html += f'''
        <div class="subject">
            <a href="/subject/{subject.id}">{subject.name}</a>
            <div class="share">{share_info}</div>
            {timer_controls}
        </div>
        '''
    html += '''
        <br><a href="/logout"><button class="logout">Logout</button></a>
    </div>
    '''
    return html

# ---------------- Logout ----------------
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ---------------- Run App ----------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)