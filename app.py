from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from flask_mysqldb import MySQL
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os
import uuid
import random
import string

app = Flask(__name__)
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Speed@2607'
app.config['MYSQL_DB'] = 'busfeesapplication'
mysql = MySQL(app)

# Folder to store generated tickets
TICKET_FOLDER = 'tickets'
if not os.path.exists(TICKET_FOLDER):
    os.makedirs(TICKET_FOLDER)
@app.route('/')
def searchbus():
    return render_template('swe.html')

@app.route('/dashboard')
def dashboard():
    return render_template('search.html')


@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        destination = request.form['destination']
        arrival = request.form['arrival']
        date = request.form['date']
    else:
        destination = request.args.get('destination', '')
        arrival = request.args.get('arrival', '')
        date = request.args.get('date', '')

    departure_times = request.args.getlist('departure_time')
    bus_types = request.args.getlist('bus_type')

    query = "SELECT * FROM bus_details WHERE destination = %s AND arrival = %s AND date = %s"
    filters = [destination, arrival, date]

    if departure_times:
        query += " AND ("
        time_conditions = []
        for time in departure_times:
            if time == 'before_6_am':
                time_conditions.append("departure_time < '06:00:00'")
            elif time == '6_am_to_12_pm':
                time_conditions.append("departure_time BETWEEN '06:00:00' AND '12:00:00'")
            elif time == '12_pm_to_6_pm':
                time_conditions.append("departure_time BETWEEN '12:00:00' AND '18:00:00'")
            elif time == 'after_6_pm':
                time_conditions.append("departure_time > '18:00:00'")
        query += " OR ".join(time_conditions)
        query += ")"

    if bus_types:
        query += " AND ("
        type_conditions = []
        for b_type in bus_types:
            type_conditions.append("bus_type = %s")
            filters.append(b_type)
        query += " OR ".join(type_conditions)
        query += ")"

    cur = mysql.connection.cursor()
    cur.execute(query, filters)
    data = cur.fetchall()
    cur.close()

    return render_template('Show.html', data=data, destination=destination, arrival=arrival, date=date, 
                           selected_departure_times=departure_times, selected_bus_types=bus_types)

@app.route('/passenger_details/<int:bus_id>')
def passenger_details(bus_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT bus_name, bus_type, seats_available FROM bus_details WHERE bus_id = %s", [bus_id])
    bus = cur.fetchone()
    
    cur.execute("SELECT seat_number, price, status FROM bus_seats WHERE bus_id = %s", [bus_id])
    seats = cur.fetchall()
    cur.close()
    
    return render_template('passenger_details.html', bus_id=bus_id, bus=bus, seats=seats)

@app.route('/registration_form/<int:bus_id>/<seat_number>')
def registration_form(bus_id, seat_number):
    return render_template('registration_form.html', bus_id=bus_id, seat_number=seat_number)
def generate_ticket_number(length):
    letters = string.ascii_lowercase
    digits = string.digits
    ticket_number = ''.join(random.choices(letters, k=length // 2)) + ''.join(random.choices(digits, k=length // 2))
    return ''.join(random.sample(ticket_number, k=length))  # Shuffle the characters

@app.route('/confirm_booking', methods=['POST'])
def confirm_booking():
    bus_id = request.form['bus_id']
    seat_number = request.form['seat_number']
    passenger_name = request.form['passenger_name']
    passenger_age = request.form['passenger_age']
    passenger_gender = request.form['passenger_gender']

    cur = mysql.connection.cursor()
    cur.execute("SELECT seats_available FROM bus_details WHERE bus_id = %s", [bus_id])
    seats_available = cur.fetchone()[0]

    if seats_available <= 0:
        return "Not enough seats available."


# Generate 6-digit alphanumeric ticket number
    ticket_number = generate_ticket_number(10)# Generate a unique ticket number
    
    cur.execute("INSERT INTO bookings (bus_id, passenger_name, passenger_age, passenger_gender, seat_number) VALUES (%s, %s, %s, %s, %s)", 
                (bus_id, passenger_name, passenger_age, passenger_gender, seat_number))

    cur.execute("UPDATE bus_details SET seats_available = seats_available - 1 WHERE bus_id = %s", [bus_id])
    cur.execute("UPDATE bus_seats SET status = 'booked' WHERE bus_id = %s AND seat_number = %s", (bus_id, seat_number))

    cur.execute("INSERT INTO tickets (ticket_number, passenger_name, bus_id, seat_number) VALUES (%s, %s, %s, %s)", 
                (ticket_number, passenger_name, bus_id, seat_number))

    mysql.connection.commit()
    cur.close()

    generate_ticket_pdf(ticket_number, passenger_name, bus_id, seat_number)
    
    return redirect(url_for('view_ticket', ticket_number=ticket_number))

@app.route('/ticket/<ticket_number>', methods=['GET', 'POST'])
def view_ticket(ticket_number):
    if request.method == 'POST':
        # Delete the ticket
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM tickets WHERE ticket_number = %s", [ticket_number])
        ticket = cur.fetchone()
        if ticket:
            bus_id = ticket['bus_id']
            seat_number = ticket['seat_number']
            # Update seat status to available
            cur.execute("UPDATE bus_seats SET status = 'available' WHERE bus_id = %s AND seat_number = %s", (bus_id, seat_number))
            # Delete the ticket
            cur.execute("DELETE FROM tickets WHERE ticket_number = %s", [ticket_number])
            mysql.connection.commit()
            cur.close()
            # Redirect to a page indicating successful deletion
            return redirect(url_for('ticket_deleted'))
        else:
            return "Ticket not found", 404
    else:
        # Fetch ticket details
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM tickets WHERE ticket_number = %s", [ticket_number])
        ticket = cur.fetchone()
        cur.close()
        
        if ticket:
            return render_template('ticket.html', ticket=ticket)
        else:
            return "Ticket not found", 404


@app.route('/download/<ticket_number>', methods=['GET'])
def download_ticket(ticket_number):
    try:
        return send_from_directory(TICKET_FOLDER, f"{ticket_number}.pdf", as_attachment=True)
    except FileNotFoundError:
        return "Ticket PDF not found", 404



def generate_ticket_pdf(ticket_number, passenger_name, bus_id, seat_number):
    pdf_path = os.path.join(TICKET_FOLDER, f"{ticket_number}.pdf")
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.drawString(100, 750, f"Ticket Number: {ticket_number}")
    c.drawString(100, 725, f"Passenger Name: {passenger_name}")
    c.drawString(100, 700, f"Bus ID: {bus_id}")
    c.drawString(100, 675, f"Seat Number: {seat_number}")
    c.save()
@app.route('/search_by_ticket_number', methods=['GET', 'POST'])
def search_by_ticket_number():
    if request.method == 'POST':
        ticket_number = request.form['ticket_number']
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM tickets WHERE ticket_number = %s", [ticket_number])
        ticket = cur.fetchone()
        cur.close()
        
        if ticket:
            return render_template('ticket.html', ticket=ticket)
        else:
            return "Ticket not found", 404
    else:
        return render_template('search_by_ticket_number.html')
@app.route('/delete_ticket', methods=['GET', 'POST'])
def delete_ticket():
    if request.method == 'POST':
        ticket_number = request.form['ticket_number']
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM tickets WHERE ticket_number = %s", [ticket_number])
        ticket = cur.fetchone()
        if ticket:
            bus_id = ticket[3]
            seat_number = ticket[4]
            
            # Update seat status to available
            cur.execute("UPDATE bus_seats SET status = 'available' WHERE bus_id = %s AND seat_number = %s", (bus_id, seat_number))
            
            # Delete the ticket
            cur.execute("DELETE FROM tickets WHERE ticket_number = %s", [ticket_number])
            
            mysql.connection.commit()
            cur.close()
            
            return "Ticket deleted successfully"
        else:
            return "Ticket not found", 404
    else:
        return render_template('delete_ticket.html')

if __name__ == '__main__':
    app.run(debug=True)
