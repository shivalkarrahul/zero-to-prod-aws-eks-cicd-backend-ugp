# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
# This step is cached if requirements.txt doesn't change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose the port your Flask app will run on (Gunicorn will bind to this)
EXPOSE 5000

# Command to run the application using Gunicorn
# 'app:app' refers to the 'app' object in 'app.py'
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
