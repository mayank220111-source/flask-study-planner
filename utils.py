from flask import session, redirect, url_for
from functools import wraps
from datetime import datetime, timedelta
from models import db, User, StudySession, Topic, Flashcard, Achievement, Badge

# Theme helpers
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

# Stats & revision helpers
def subject_stats(user_id):
    from sqlalchemy.orm import joinedload
    
    subjects = []
    total_progress = 0
    total_topics = 0
    completed_topics = 0
    total_study_time = 0
    
    # Use eager loading to prevent N+1 queries
    subjects_data = Subject.query.options(
        joinedload(Subject.chapters).joinedload(Chapter.topics)
    ).filter_by(user_id=user_id).all()
    
    for subject in subjects_data:
        total_subject_topics = 0
        completed_subject_topics = 0
        
        for chapter in subject.chapters:
            topics = chapter.topics  # Already loaded due to eager loading
            total_subject_topics += len(topics)
            completed_subject_topics += sum(1 for t in topics if t.status == 'completed')
        
        total_topics += total_subject_topics
        completed_topics += completed_subject_topics
        
        progress = int((completed_subject_topics / total_subject_topics * 100)) if total_subject_topics > 0 else 0
        total_progress += progress
        
        # Calculate study time for this subject (already loaded)
        study_time = sum(session.duration_minutes for session in subject.study_sessions if session.duration_minutes)
        total_study_time += study_time
        
        subjects.append({
            'id': subject.id,
            'name': subject.name,
            'progress': progress,
            'total_topics': total_subject_topics,
            'completed_topics': completed_subject_topics,
            'study_time': study_time,
            'color': subject.color
        })
    
    return {
        'subjects': subjects,
        'total_progress': int(total_progress / len(subjects)) if subjects else 0,
        'total_topics': total_topics,
        'completed_topics': completed_topics,
        'total_study_time': total_study_time
    }

def revision_tip(chapter):
    if not chapter.last_studied:
        return "Start studying this chapter today!"
    
    days_since = (datetime.utcnow() - chapter.last_studied).days
    if days_since < 3:
        return "You just studied this! Review in a couple days."
    elif days_since < 7:
        return "Time for a quick review to reinforce learning."
    elif days_since < 14:
        return "Good time for a thorough revision session."
    else:
        return "Urgent! This chapter needs your attention."

# Gamification helpers
def calculate_level(points):
    """Calculate user level based on points"""
    return int(points / 100) + 1

def update_user_points(user, points_to_add):
    """Update user points and check for level up"""
    old_level = user.level
    user.points += points_to_add
    user.level = calculate_level(user.points)
    
    if user.level > old_level:
        # User leveled up - grant a badge
        grant_badge(user, 'level_up', f'Reached Level {user.level}!')
    
    db.session.commit()
    return user.level > old_level

def update_streak(user):
    """Update and return user's study streak"""
    today = datetime.utcnow().date()
    
    if user.last_study_date:
        last_date = user.last_study_date.date()
        days_diff = (today - last_date).days
        
        if days_diff == 1:
            user.streak += 1
            # Check for streak achievements
            if user.streak == 7:
                grant_badge(user, 'week_streak', '7-day study streak!')
            elif user.streak == 30:
                grant_badge(user, 'month_streak', '30-day study streak!')
        elif days_diff > 1:
            user.streak = 1  # Reset streak
    else:
        user.streak = 1  # First study session
    
    user.last_study_date = datetime.utcnow()
    db.session.commit()
    return user.streak

def grant_badge(user, badge_type, description):
    """Grant a badge to a user"""
    existing_badge = Badge.query.filter_by(
        user_id=user.id,
        name=badge_type
    ).first()
    
    if not existing_badge:
        badge_icons = {
            'level_up': '🎖️',
            'week_streak': '🔥',
            'month_streak': '💎',
            'first_topic': '⭐',
            'topics_master': '🏆',
            'flashcard_master': '🧠',
            'study_warrior': '⚔️'
        }
        
        badge = Badge(
            user_id=user.id,
            name=badge_type,
            description=description,
            icon=badge_icons.get(badge_type, '🏅')
        )
        db.session.add(badge)
        db.session.commit()
        return True
    return False

def check_achievements(user):
    """Check and award achievements"""
    achievements = []
    
    # Check for first completed topic
    completed_topics = Topic.query.filter_by(status='completed').join(
        Chapter
    ).join(
        Subject
    ).filter_by(user_id=user.id).count()
    
    if completed_topics == 1:
        grant_badge(user, 'first_topic', 'Completed your first topic!')
        achievements.append('First Topic Completed')
    
    # Check for topics master (100 topics)
    if completed_topics >= 100:
        grant_badge(user, 'topics_master', 'Completed 100 topics!')
        achievements.append('Topics Master')
    
    # Check for flashcard mastery
    mastered_flashcards = Flashcard.query.join(
        Topic
    ).join(
        Chapter
    ).join(
        Subject
    ).filter_by(user_id=user.id).filter(
        Flashcard.mastery_level >= 5
    ).count()
    
    if mastered_flashcards >= 50:
        grant_badge(user, 'flashcard_master', 'Mastered 50 flashcards!')
        achievements.append('Flashcard Master')
    
    # Check for study warrior (100 hours of study)
    total_study_hours = sum(
        session.duration_minutes for session in StudySession.query.filter_by(user_id=user.id).all()
    ) / 60
    
    if total_study_hours >= 100:
        grant_badge(user, 'study_warrior', 'Studied for 100 hours!')
        achievements.append('Study Warrior')
    
    return achievements

def get_user_achievements(user):
    """Get all user achievements and statistics"""
    from sqlalchemy.orm import joinedload
    
    return {
        'points': user.points,
        'level': user.level,
        'streak': user.streak,
        'badges': Badge.query.filter_by(user_id=user.id).order_by(Badge.earned_at.desc()).all(),
        'completed_topics': Topic.query.filter_by(status='completed').join(
            Chapter
        ).join(
            Subject
        ).filter_by(user_id=user.id).count(),
        'mastered_flashcards': Flashcard.query.join(
            Topic
        ).join(
            Chapter
        ).join(
            Subject
        ).filter_by(user_id=user.id).filter(
            Flashcard.mastery_level >= 5
        ).count(),
        'total_study_hours': sum(
            session.duration_minutes for session in StudySession.query.filter_by(user_id=user.id).all()
        ) / 60
    }

# Spaced repetition algorithm for flashcards
def calculate_next_review(mastery_level, review_count):
    """Calculate next review date using spaced repetition"""
    intervals = [1, 3, 7, 14, 30, 60]  # Days based on mastery level (0-5)
    
    if mastery_level < len(intervals):
        days = intervals[mastery_level]
    else:
        days = 90  # Maximum interval
    
    return datetime.utcnow() + timedelta(days=days)

def update_flashcard_mastery(flashcard, correct):
    """Update flashcard mastery based on review result"""
    flashcard.review_count += 1
    
    if correct:
        flashcard.mastery_level = min(flashcard.mastery_level + 1, 5)
    else:
        flashcard.mastery_level = max(flashcard.mastery_level - 1, 0)
    
    flashcard.next_review = calculate_next_review(
        flashcard.mastery_level,
        flashcard.review_count
    )
    
    db.session.commit()
    return flashcard.mastery_level

# Decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Data export/import helpers
def export_user_data(user):
    """Export user data as JSON"""
    from json import dumps
    data = {
        'user': {
            'username': user.username,
            'theme': user.theme,
            'points': user.points,
            'streak': user.streak,
            'level': user.level
        },
        'subjects': [],
        'reminders': [],
        'study_events': []
    }
    
    for subject in user.subjects:
        subject_data = {
            'name': subject.name,
            'color': subject.color,
            'chapters': []
        }
        
        for chapter in subject.chapters:
            chapter_data = {
                'name': chapter.name,
                'topics': []
            }
            
            for topic in chapter.topics:
                topic_data = {
                    'name': topic.name,
                    'status': topic.status,
                    'progress': topic.progress,
                    'notes': topic.notes,
                    'flashcards': []
                }
                
                for flashcard in topic.flashcards:
                    topic_data['flashcards'].append({
                        'front': flashcard.front,
                        'back': flashcard.back,
                        'mastery_level': flashcard.mastery_level
                    })
                
                chapter_data['topics'].append(topic_data)
            
            subject_data['chapters'].append(chapter_data)
        
        data['subjects'].append(subject_data)
    
    for reminder in user.reminders:
        data['reminders'].append({
            'title': reminder.title,
            'description': reminder.description,
            'reminder_time': reminder.reminder_time.isoformat(),
            'repeat': reminder.repeat
        })
    
    return dumps(data, indent=2)

def get_due_flashcards(user):
    """Get flashcards due for review"""
    from models import Flashcard, Topic, Chapter, Subject
    return Flashcard.query.join(
        Topic
    ).join(
        Chapter
    ).join(
        Subject
    ).filter(
        Subject.user_id == user.id,
        Flashcard.next_review <= datetime.utcnow()
    ).all()