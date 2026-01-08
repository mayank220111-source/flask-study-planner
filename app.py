from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///study.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    chapters = db.relationship('Chapter', backref='subject', lazy=True)

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)

with app.app_context():
    db.create_all()

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        if 'subject' in request.form:
            subject_name = request.form["subject"]
            new_subject = Subject(name=subject_name)
            db.session.add(new_subject)
        elif 'chapter' in request.form:
            chapter_name = request.form["chapter"]
            subject_id = request.form["subject_id"]
            new_chapter = Chapter(name=chapter_name, subject_id=subject_id)
            db.session.add(new_chapter)
        db.session.commit()
        return redirect(url_for("home"))
    
    subjects = Subject.query.all()
    return render_template("index.html", subjects=subjects)

if __name__ == "__main__":
    app.run(debug=True)
