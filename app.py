# app.py
from flask import Flask, jsonify, request
import os
import boto3
import uuid # For generating unique IDs for messages
import time # For timestamp
from flask_cors import CORS # Import CORS

app = Flask(__name__)
# Initialize CORS for your app.
# By default, CORS(app) allows all origins, which is good for initial testing.
# For production, you should restrict this to your S3 static website hosting endpoint.
# Example: CORS(app, resources={r"/*": {"origins": "http://your-frontend-s3-bucket-name.s3-website-us-east-1.amazonaws.com"}})
CORS(app)


# --- DynamoDB Initialization ---
# Get DynamoDB table name from environment variable
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME', 'ugp-eks-cicd-messages-table') # Default to a common name
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1') # Default to us-east-1

try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    print(f"DynamoDB table '{DYNAMODB_TABLE_NAME}' initialized successfully.")
except Exception as e:
    print(f"ERROR: Failed to initialize DynamoDB table '{DYNAMODB_TABLE_NAME}': {e}")
    # In a real application, you might want to exit or use a fallback here.

# --- End DynamoDB Initialization ---

@app.route('/api/hello', methods=['GET'])
def hello():
    """
    Existing hello endpoint.
    """
    return jsonify(message="Hello from the AWS UGP backend!", environment=os.environ.get('APP_ENVIRONMENT', 'development'))

@app.route('/messages', methods=['GET', 'POST']) # Combined GET and POST for /messages
def handle_messages():
    """
    Handles both GET and POST requests for messages.
    GET: Retrieves all messages from DynamoDB.
    POST: Receives a new message from the UI and stores it in DynamoDB.
    """
    if request.method == 'GET':
        try:
            response = table.scan()
            messages = []
            # Sort messages by timestamp if present, as scan doesn't guarantee order
            sorted_items = sorted(response.get('Items', []), key=lambda x: x.get('timestamp', 0))

            for item in sorted_items:
                messages.append({
                    "id": item.get("id"),
                    "text": item.get("text", "No text provided"),
                    "timestamp": item.get("timestamp")
                })
            return jsonify(messages), 200
        except Exception as e:
            print(f"Error fetching messages from DynamoDB: {e}")
            return jsonify(error="Failed to retrieve messages"), 500

    elif request.method == 'POST':
        if not request.is_json:
            return jsonify(error="Request must be JSON"), 400

        data = request.get_json()
        message_text = data.get('text')

        if not message_text:
            return jsonify(error="'text' field is required"), 400

        try:
            message_id = str(uuid.uuid4()) # Generate a unique ID for the message
            current_timestamp = int(time.time()) # Unix timestamp for sorting

            item = {
                'id': message_id,
                'text': message_text,
                'timestamp': current_timestamp
            }
            table.put_item(Item=item)
            return jsonify(id=message_id, text=message_text, message="Message posted successfully"), 201
        except Exception as e:
            print(f"Error posting message to DynamoDB: {e}")
            return jsonify(error="Failed to post message"), 500
    
    # Fallback for unsupported methods (though Flask handles this for defined methods)
    return jsonify(error="Method Not Allowed"), 405


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
