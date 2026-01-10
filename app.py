from flask import Flask, render_template_string, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'key123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///study.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(100))

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    youtube_link = db.Column(db.String(200))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['username']).first():
            return '<h2>User exists</h2><a href="/register">Back</a>'
        user = User(username=request.form['username'], password=generate_password_hash(request.form['password']))
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return '''
    <style>
        body { font-family: Arial; margin: 40px; background: #f0f0f0; }
        h2 { color: #333; }
        input { padding: 8px; margin: 5px 0; width: 200px; }
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
        input { padding: 8px; margin: 5px 0; width: 200px; }
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

@app.route('/')
@login_required
def home():
    subjects = Subject.query.filter_by(user_id=current_user.id).all()
    html = '''
    <style>
        body { font-family: Arial; margin: 20px; background: #f5f5f5; }
        h1 { color: #2c3e50; text-align: center; }
        .container { max-width: 1000px; margin: 0 auto; }
        .subject { background: #3498db; color: white; padding: 15px; margin: 10px 0; border-radius: 5px; cursor: pointer; }
        .subject:hover { background: #2980b9; }
        .subject-form { background: white; padding: 15px; margin: 20px 0; border: 2px solid #3498db; border-radius: 5px; }
        input, button { padding: 8px; margin: 5px; }
        button { background: #27ae60; color: white; border: none; cursor: pointer; border-radius: 3px; }
        button:hover { background: #229954; }
        .logout { background: #e74c3c; float: right; }
        .logout:hover { background: #c0392b; }
    </style>
    <div class="container">
        <h1>📚 CBSE Study Planner - ''' + current_user.username + '''</h1>
        
        <div class="subject-form">
            <h3>Add Subject</h3>
            <form method="post" action="/add_subject">
                Subject Name: <input name="subject_name" placeholder="Physics, Chemistry, Maths...">
                <button type="submit">Add Subject</button>
            </form>
        </div>
        
        <h2>Your Subjects</h2>
    '''
    for subject in subjects:
        html += '<div class="subject">' + subject.name + '</div>'
    html += '<br><a href="/logout"><button class="logout">Logout</button></a>'
    html += '</div>'
    return html

@app.route('/add_subject', methods=['POST'])
@login_required
def add_subject():
    name = request.form['subject_name']
    if name:
        subject = Subject(name=name, user_id=current_user.id)
        db.session.add(subject)
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
