from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, index=True)  # Add index
    password = db.Column(db.String(100))
    theme = db.Column(db.String(10), default='light')  # 'light' or 'dark'
    
    # Gamification fields
    points = db.Column(db.Integer, default=0)
    streak = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=0, index=True)  # Add index for leaderboard
    last_study_date = db.Column(db.DateTime, index=True)  # Add index for streak calculations
    
    # Relationships
    subjects = db.relationship('Subject', backref='user', lazy=True, cascade='all, delete-orphan')
    badges = db.relationship('Badge', backref='user', lazy=True, cascade='all, delete-orphan')
    reminders = db.relationship('Reminder', backref='user', lazy=True, cascade='all, delete-orphan')
    achievements = db.relationship('Achievement', backref='user', lazy=True, cascade='all, delete-orphan')

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)  # Add index
    share_token = db.Column(db.String(64), unique=True, nullable=True, index=True)  # Add index for sharing
    color = db.Column(db.String(7), default='#3498db')  # hex color code
    
    # Relationships
    chapters = db.relationship('Chapter', backref='subject', lazy=True, cascade='all, delete-orphan')
    study_sessions = db.relationship('StudySession', backref='subject', lazy=True, cascade='all, delete-orphan')

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    last_studied = db.Column(db.DateTime, nullable=True)  # for revision schedule
    
    # Relationships
    topics = db.relationship('Topic', backref='chapter', lazy=True, cascade='all, delete-orphan')
    questions = db.relationship('Question', backref='chapter', lazy=True, cascade='all, delete-orphan')

class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    status = db.Column(db.String(20), default='not_started', index=True)  # Add index for filtering
    progress = db.Column(db.Integer, default=0)               # 0-100
    notes = db.Column(db.Text, default='')
    
    # Relationships
    flashcards = db.relationship('Flashcard', backref='topic', lazy=True, cascade='all, delete-orphan')

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    text = db.Column(db.Text)
    difficulty = db.Column(db.String(20), default='medium')  # easy, medium, hard

class Flashcard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'))
    front = db.Column(db.Text)  # question/formula name
    back = db.Column(db.Text)   # answer/formula
    next_review = db.Column(db.DateTime, nullable=True, index=True)  # Add index for spaced repetition
    review_count = db.Column(db.Integer, default=0)
    mastery_level = db.Column(db.Integer, default=0, index=True)  # Add index for filtering by mastery

class StudySession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)  # Add index
    start_time = db.Column(db.DateTime, nullable=False, index=True)  # Add index for time-based queries
    end_time = db.Column(db.DateTime, nullable=True, index=True)  # Add index
    duration_minutes = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, default='')

class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)  # Add index
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'), nullable=True)
    title = db.Column(db.String(200))
    description = db.Column(db.Text, default='')
    reminder_time = db.Column(db.DateTime, nullable=False, index=True)  # Add index for time-based queries
    is_completed = db.Column(db.Boolean, default=False, index=True)  # Add index
    repeat = db.Column(db.String(20), default='once')  # once, daily, weekly, monthly

class Badge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    name = db.Column(db.String(100))
    description = db.Column(db.Text)
    icon = db.Column(db.String(50))  # emoji or icon code
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)

class Achievement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    type = db.Column(db.String(50))  # topics_completed, study_time, flashcards_mastered, etc.
    value = db.Column(db.Integer)
    description = db.Column(db.Text)
    achieved_at = db.Column(db.DateTime, default=datetime.utcnow)

class StudyEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)  # Add index
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))
    title = db.Column(db.String(200))
    description = db.Column(db.Text, default='')
    event_date = db.Column(db.Date, nullable=False, index=True)  # Add index for calendar queries
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    event_type = db.Column(db.String(50), default='study')  # study, exam, revision, etc.