# app.py
from flask import Flask, jsonify, request
import os
import boto3
import uuid # For generating unique IDs for messages
import time # For timestamp
from flask_cors import CORS # Import CORS
import json # For handling JSON payloads

app = Flask(__name__)
# Initialize CORS for your app.
# By default, CORS(app) allows all origins, which is good for initial testing.
# For production, you should restrict this to your frontend's domain.
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

# --- AWS LLM Integration ---
def generate_quote_with_aws_llm(name, input1, input2, input3):
    """
    Generates a funny quote using Amazon Bedrock with the Anthropic Claude 3 Sonnet model.
    The implementation is based on the user's provided reference code.
    """
    bedrock_client = boto3.client(
        service_name='bedrock-runtime',
        region_name=AWS_REGION
    )

    prompt = f"Generate a very short, funny, and ridiculous quote about a person named {name}, involving a {input1}, a {input2}, and an {input3}. The quote should be no more than 25 words. It should be in the style of a wise, but slightly absurd, old sage."
    
    try:
        # Construct the payload for the Anthropic Messages API
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 200,
            "temperature": 1,
            "top_k": 50,
            "top_p": 0.9,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}]
                }
            ]
        })
        model_id = 'anthropic.claude-3-sonnet-20240229-v1:0'
        
        response = bedrock_client.invoke_model(
            body=body,
            modelId=model_id,
            accept='application/json',
            contentType='application/json'
        )

        response_body = json.loads(response.get('body').read())
        
        # Extract the generated text from the response
        generated_quote = response_body['content'][0]['text']
        
        return generated_quote
        
    except Exception as e:
        print(f"Error calling AWS LLM: {e}")
        return "Could not generate a quote. The LLM is unavailable."
# --- End AWS LLM Integration ---

@app.route('/api/hello', methods=['GET'])
def hello():
    """
    Existing hello endpoint.
    """
    return jsonify(message="Hello from the AWS UGP backend!", environment=os.environ.get('APP_ENVIRONMENT', 'development'))

@app.route('/messages', methods=['GET', 'POST'])
def handle_quotes():
    """
    Handles both GET and POST requests for quotes.
    GET: Retrieves all quotes from DynamoDB.
    POST: Receives inputs, generates a quote with an AWS LLM, and stores it in DynamoDB.
    """
    if request.method == 'GET':
        try:
            response = table.scan()
            quotes = []
            # We'll filter for items that have a 'quote' field.
            sorted_items = sorted(response.get('Items', []), key=lambda x: x.get('timestamp', 0), reverse=True)

            for item in sorted_items:
                if 'quote' in item:
                    quotes.append({
                        "id": item.get("id"),
                        "name": item.get("name", "Unknown"),
                        "quote": item.get("quote", "No quote provided")
                    })
            return jsonify(quotes), 200
        except Exception as e:
            print(f"Error fetching quotes from DynamoDB: {e}")
            return jsonify(error="Failed to retrieve quotes"), 500

    elif request.method == 'POST':
        if not request.is_json:
            return jsonify(error="Request must be JSON"), 400

        data = request.get_json()
        name = data.get('name')
        input1 = data.get('input1')
        input2 = data.get('input2')
        input3 = data.get('input3')

        if not all([name, input1, input2, input3]):
            return jsonify(error="All fields (name, input1, input2, input3) are required"), 400
        
        try:
            # 1. Generate the quote using your AWS LLM implementation
            generated_quote = generate_quote_with_aws_llm(name, input1, input2, input3)
            
            # 2. Store the new quote in DynamoDB
            quote_id = str(uuid.uuid4())
            current_timestamp = int(time.time())
            
            item = {
                'id': quote_id,
                'name': name,
                'quote': generated_quote,
                'timestamp': current_timestamp
            }
            
            table.put_item(Item=item)
            
            return jsonify(id=quote_id, name=name, quote=generated_quote, message="Quote generated and posted successfully"), 201
            
        except Exception as e:
            print(f"Error processing quote request: {e}")
            return jsonify(error="Failed to generate or post quote"), 500
    
    return jsonify(error="Method Not Allowed"), 405


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
