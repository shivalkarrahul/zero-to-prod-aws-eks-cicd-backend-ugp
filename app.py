# app.py
from flask import Flask, jsonify, request
import os
import boto3
import uuid  # For generating unique IDs for messages
import time  # For timestamp
from flask_cors import CORS  # Import CORS
import json  # For handling JSON payloads
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
import traceback

app = Flask(__name__)
# Initialize CORS for your app.
CORS(app)

print("INFO: Flask application starting up...")

# --- DynamoDB Initialization ---
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME', 'ugp-eks-cicd-messages-table')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

print(f"INFO: Initializing DynamoDB resource for table '{DYNAMODB_TABLE_NAME}' in region '{AWS_REGION}'...")
try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    print(f"INFO: DynamoDB table '{DYNAMODB_TABLE_NAME}' resource initialized successfully.")
except Exception as e:
    print(f"FATAL: Failed to initialize DynamoDB table '{DYNAMODB_TABLE_NAME}': {e}")

# --- End DynamoDB Initialization ---

# --- AWS LLM Integration ---
def generate_quote_with_aws_llm(name, input1, input2, input3):
    """
    Generates a funny quote using Amazon Bedrock with the Anthropic Claude 3 Sonnet model.
    Includes verbose logging for each step of the LLM invocation.
    """
    print("INFO: Preparing to invoke AWS Bedrock LLM...")
    try:
        bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=AWS_REGION
        )
        print("INFO: Bedrock client created successfully.")

        prompt = f"Generate a very short, funny, and ridiculous quote about a person named {name}, involving a {input1}, a {input2}, and an {input3}. The quote should be no more than 25 words. It should be in the style of a wise, but slightly absurd, old sage."
        print(f"INFO: Using prompt: '{prompt}'")

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
        
        print(f"INFO: Invoking model '{model_id}' with payload: {body}")
        
        response = bedrock_client.invoke_model(
            body=body,
            modelId=model_id,
            accept='application/json',
            contentType='application/json'
        )

        print("INFO: Received response from Bedrock LLM. Reading body...")
        response_body = json.loads(response.get('body').read())
        print(f"DEBUG: Raw response body from Bedrock: {response_body}")
        
        # Extract the generated text from the response
        if 'content' not in response_body or not response_body['content'] or 'text' not in response_body['content'][0]:
            print("ERROR: Unexpected response structure from Bedrock.")
            return "Could not generate a quote. Unexpected LLM response."

        generated_quote = response_body['content'][0]['text']
        print(f"INFO: Successfully generated quote: '{generated_quote}'")
        
        return generated_quote
        
    except ClientError as e:
        print(f"ERROR: AWS ClientError when invoking Bedrock LLM: {e}")
        traceback.print_exc()
        return "Could not generate a quote. An AWS client error occurred."
    except Exception as e:
        print(f"ERROR: Unhandled exception when invoking Bedrock LLM: {e}")
        traceback.print_exc()
        return "Could not generate a quote. The LLM is unavailable."

# --- End AWS LLM Integration ---

@app.route('/messages', methods=['GET', 'POST'])
def handle_quotes():
    """
    Handles both GET and POST requests for quotes, with all logic for this route.
    GET: Retrieves all quotes from DynamoDB.
    POST: Receives inputs, generates a quote with an AWS LLM, and stores it in DynamoDB.
    """
    print(f"INFO: Received {request.method} request for /messages")
    if request.method == 'GET':
        try:
            print("INFO: Scanning DynamoDB for quotes...")
            response = table.scan(
                FilterExpression=Attr('quote').exists()
            )
            quotes = []
            sorted_items = sorted(response.get('Items', []), key=lambda x: x.get('timestamp', 0), reverse=True)

            for item in sorted_items:
                quotes.append({
                    "id": item.get("id"),
                    "name": item.get("name", "Unknown"),
                    "quote": item.get("quote", "No quote provided")
                })
            print(f"INFO: Retrieved {len(quotes)} quotes from DynamoDB.")
            return jsonify(quotes), 200
        except Exception as e:
            print(f"ERROR: Error fetching quotes from DynamoDB: {e}")
            traceback.print_exc()
            return jsonify(error="Failed to retrieve quotes"), 500

    elif request.method == 'POST':
        print("INFO: Processing POST request for new quote.")
        if not request.is_json:
            print("ERROR: Request is not JSON.")
            return jsonify(error="Request must be JSON"), 400

        data = request.get_json()
        print(f"INFO: Received JSON payload: {data}")
        name = data.get('name')
        input1 = data.get('input1')
        input2 = data.get('input2')
        input3 = data.get('input3')

        if not all([name, input1, input2, input3]):
            print("ERROR: Missing required fields in POST request for a quote.")
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
            
            print(f"INFO: Storing new quote in DynamoDB with ID '{quote_id}'...")
            table.put_item(Item=item)
            print("INFO: Quote successfully stored in DynamoDB.")
            
            return jsonify(id=quote_id, name=name, quote=generated_quote, message="Quote generated and posted successfully"), 201
            
        except Exception as e:
            print(f"ERROR: Unhandled exception during quote POST request: {e}")
            traceback.print_exc()
            return jsonify(error="Failed to generate or post quote"), 500
    
    return jsonify(error="Method Not Allowed"), 405


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
