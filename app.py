import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from datetime import datetime
from threading import Thread # Use threading for non-blocking email sending

# --- Configuration ---
# Note: For production, set SECRET_KEY, MAIL_SERVER, etc., as environment variables.
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_secret_key_for_dev')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///incidents.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email Configuration (REQUIRED for notifications - REPLACE with your actual SMTP credentials)
# NOTE: Using a real SMTP server (like Gmail) requires an App Password, not your regular password.
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com') 
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'sohafarzeen@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'smmaxlkxcyklnljj') 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'sohafarzeen@gmail.com')

# --- Initialization ---
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)

# --- Models ---
class User(UserMixin, db.Model):
    """Database model for application users."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    # Role: 1=Admin/Manager, 2=Technician, 3=Reporter
    role = db.Column(db.Integer, default=3) 
    email = db.Column(db.String(120), default="") 

class Incident(db.Model):
    """Database model for tracking incidents."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='New', nullable=False)
    priority = db.Column(db.String(10), default='Medium', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

# --- User Loader for Flask-Login ---
@login_manager.user_loader
def load_user(user_id):
    """Loads a user from the database based on ID."""
    return db.session.get(User, int(user_id))

# --- Email Notification Function (NON-BLOCKING) ---
def async_send_mail(app, msg):
    """Wraps mail.send in a separate thread."""
    with app.app_context():
        try:
            mail.send(msg)
            print(f"Async Notification sent successfully to {msg.recipients}")
        except Exception as e:
            print(f"Async Email failed to send: {e}")
            
def send_notification(incident, recipient_email, subject, body):
    """Initiates an asynchronous email notification."""
    try:
        msg = Message(subject, recipients=[recipient_email])
        msg.body = body
        
        # Start the email sending in a background thread to prevent the web request from hanging
        Thread(target=async_send_mail, args=(app, msg)).start()
        
    except Exception as e:
        print(f"Error initiating email thread: {e}")

# --- Utility Functions ---
def is_manager():
    """Checks if the current user has the Manager/Admin role (role=1)."""
    return current_user.is_authenticated and current_user.role == 1

def is_technician():
    """Checks if the current user has the Technician role (role=2 or 1)."""
    return current_user.is_authenticated and current_user.role in [1, 2]

# --- Routes (REST API functionality combined with UI rendering) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login (simple username check for demo)."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()
        
        # Simple authentication: just check if the user exists
        if user:
            login_user(user)
            flash(f'Logged in as {user.username} (Role: {user.role})', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username. Please try again.', 'danger')
            
    # Note: Using the same incident_portal.html for simplicity
    return render_template('incident_portal.html', is_login_page=True, current_user_id=None)

@app.route('/logout')
@login_required
def logout():
    """Logs the current user out."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    """Displays the list of all incidents."""
    incidents = Incident.query.order_by(Incident.created_at.desc()).all()
    users = User.query.all()
    # Map IDs to usernames for display
    user_map = {u.id: u.username for u in users}

    return render_template('incident_portal.html', 
                            incidents=incidents, 
                            users=users,
                            user_map=user_map,
                            is_manager=is_manager(),
                            is_technician=is_technician(),
                            is_login_page=False,
                            current_user_id=current_user.id)

# API/Route to Create a new incident
@app.route('/incident/new', methods=['POST'])
@login_required
def create_incident():
    """Handles the creation of a new incident."""
    title = request.form.get('title')
    description = request.form.get('description')
    priority = request.form.get('priority')
    
    if not title or not description or not priority:
        flash('All fields are required to create an incident.', 'danger')
        return redirect(url_for('index'))

    new_incident = Incident(
        title=title, 
        description=description, 
        priority=priority, 
        reporter_id=current_user.id
    )
    db.session.add(new_incident)
    db.session.commit()
    
    flash(f'Incident "{title}" created successfully.', 'success')
    
    # Send a notification to the Admins/Managers 
    admin_users = User.query.filter_by(role=1).all()
    
    subject = f"[IMS] NEW Incident #{new_incident.id} - {new_incident.priority}: {new_incident.title}"
    body = (f"A new incident has been reported by {current_user.username}:\n\n"
            f"Title: {new_incident.title}\n"
            f"Priority: {new_incident.priority}\n"
            f"Description: {new_incident.description}\n\n"
            f"Status: New - Please assign and start resolution.")
            
    for user in admin_users:
        if user.email:
            send_notification(new_incident, user.email, subject, body)
    
    return redirect(url_for('index'))

# API/Route to Assign or Update an incident (Manager/Admin access required)
@app.route('/incident/update/<int:incident_id>', methods=['POST'])
@login_required
def update_incident(incident_id):
    """Handles updating the status and assignment of an incident."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        flash('Incident not found.', 'danger')
        return redirect(url_for('index'))

    if not is_technician():
        flash('Permission denied. Only managers or technicians can update incidents.', 'danger')
        return redirect(url_for('index'))
    
    new_status = request.form.get('status')
    assigned_user_id = request.form.get('assigned_to_id')
    
    # Store old values for notification comparison
    old_status = incident.status
    old_assignee_id = incident.assigned_to_id
    
    # 1. Update Status
    if new_status and new_status != incident.status:
        incident.status = new_status
        flash(f'Incident #{incident_id} status updated to {new_status}.', 'info')
    
    # 2. Update Assignment
    if assigned_user_id is not None:
        assigned_user_id = int(assigned_user_id) if assigned_user_id and assigned_user_id.isdigit() and int(assigned_user_id) > 0 else None
        
        # Only Managers (role=1) can assign to someone else. Technicians (role=2) can only self-assign.
        if assigned_user_id != incident.assigned_to_id:
            if is_manager() or assigned_user_id == current_user.id:
                incident.assigned_to_id = assigned_user_id
                
            else:
                flash('Permission denied. You can only self-assign or unassign.', 'danger')
                
    db.session.commit()
    
    # --- Notification Logic ---
    
    # A. Assignment Change Notification
    if incident.assigned_to_id != old_assignee_id:
        if incident.assigned_to_id: # Newly assigned
            assigned_user = User.query.filter_by(id=incident.assigned_to_id).first()
            if assigned_user and assigned_user.email:
                subject = f"[IMS] Incident #{incident_id} Assigned to You: {incident.title}"
                body = (f"Incident #{incident_id} has been assigned to you by {current_user.username}.\n\n"
                        f"Title: {incident.title}\n"
                        f"Priority: {incident.priority}\n"
                        f"Status: {incident.status}\n\n"
                        f"Please review and update the status accordingly.")
                send_notification(incident, assigned_user.email, subject, body)
                flash(f'Assignment notification sent to {assigned_user.username}.', 'success')
        
        elif old_assignee_id: # Unassigned
            old_assignee = User.query.filter_by(id=old_assignee_id).first()
            if old_assignee and old_assignee.email:
                subject = f"[IMS] Incident #{incident_id} Unassigned: {incident.title}"
                body = f"Incident #{incident_id} has been unassigned by {current_user.username}."
                send_notification(incident, old_assignee.email, subject, body)
    
    # B. Status Change Notification (Notify Reporter and Assignee)
    if incident.status != old_status:
        # Notify Reporter
        reporter = User.query.filter_by(id=incident.reporter_id).first()
        if reporter and reporter.email:
            subject = f"[IMS] Incident #{incident_id} Status Updated to {incident.status}"
            body = (f"The status of your reported incident has been updated to {incident.status} by {current_user.username}.\n\n"
                    f"Title: {incident.title}\n"
                    f"Description: {incident.description}\n\n"
                    f"Thank you for your report.")
            send_notification(incident, reporter.email, subject, body)

        # Notify Assignee (if status changed by someone else, like a Manager closing a ticket)
        if incident.assigned_to_id and incident.assigned_to_id != current_user.id:
            assignee = User.query.filter_by(id=incident.assigned_to_id).first()
            if assignee and assignee.email:
                subject = f"[IMS] Incident #{incident_id} Status Change: {incident.status}"
                body = f"The status of your assigned incident has been updated to {incident.status} by {current_user.username}."
                send_notification(incident, assignee.email, subject, body)

    return redirect(url_for('index'))

# API/Route to Delete an incident (Admin access required)
@app.route('/incident/delete/<int:incident_id>', methods=['POST'])
@login_required
def delete_incident(incident_id):
    """Handles the deletion of an incident."""
    incident = db.session.get(Incident, incident_id)
    if not incident:
        flash('Incident not found.', 'danger')
        return redirect(url_for('index'))
        
    if not is_manager():
        flash('Permission denied. Only managers can delete incidents.', 'danger')
        return redirect(url_for('index'))

    db.session.delete(incident)
    db.session.commit()
    flash(f'Incident #{incident_id} deleted successfully.', 'warning')
    return redirect(url_for('index'))

# --- Database Setup (Run once to create tables and seed users) ---
@app.cli.command('initdb')
def initdb_command():
    """Initializes the database and seeds initial user accounts."""
    with app.app_context():
        # Temporarily add 'email' field to the User model seed data
        db.create_all()
        
        # Seed Users: Admin, Technician, Reporter
        if not User.query.first():
            # NOTE: For LIVE testing, replace the three placeholder emails below with three real email addresses you can access.
            user1 = User(username='admin', role=1, email='sohafarzee@gmail.com') 
            user2 = User(username='tech_alice', role=2, email='sabahathsiddiqua@gmail.com')
            user3 = User(username='reporter_bob', role=3, email='22cse056@bnmit.in')
            db.session.add_all([user1, user2, user3])
            db.session.commit()
            print('Database created and users seeded: admin, tech_alice, reporter_bob (with placeholder emails).')
        else:
            print('Database already exists and users are present.')
        
if __name__ == '__main__':
    # When running directly (not via 'flask run')
    with app.app_context():
        # Ensure database is created on first run if not using initdb
        if not os.path.exists('instance/incidents.db'):
            db.create_all()
            
    app.run(debug=True)
