# app.py
from flask import Flask, jsonify, request
import os
import boto3
import uuid
import time
from flask_cors import CORS
import json
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
import traceback
import logging

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

app = Flask(__name__)
CORS(app)

logging.info("Flask application starting up...")

# --- DynamoDB Initialization ---
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME', 'ugp-eks-cicd-messages-table')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

logging.info(f"Initializing DynamoDB resource for table '{DYNAMODB_TABLE_NAME}' in region '{AWS_REGION}'...")
try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    logging.info(f"DynamoDB table '{DYNAMODB_TABLE_NAME}' resource initialized successfully.")
except Exception as e:
    logging.fatal(f"Failed to initialize DynamoDB table '{DYNAMODB_TABLE_NAME}': {e}")

# --- End DynamoDB Initialization ---

# --- AWS LLM Integration ---
def generate_quote_with_aws_llm(name, input1, input2, input3):
    """
    Generates a funny quote using Amazon Bedrock with the Anthropic Claude 3 Sonnet model.
    """
    logging.info("Preparing to invoke AWS Bedrock LLM...")
    try:
        bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=AWS_REGION
        )
        logging.info("Bedrock client created successfully.")

        prompt = f"You are a witty desi Gen Z roast master with perfect meme timing. Write one short, hilarious roast (max 25 words) about someone named {name}, involving {input1}, {input2}, and {input3}. Make it sound like a viral Instagram meme or reel caption — sarcastic, visual, and instantly relatable. The humor should be sharp but safe, like how friends roast each other in college group chats. No vulgarity, no adult jokes, no politics, no slurs. Use Hinglish. Only output the roast quote. Nothing else."
        logging.info(f"Using prompt: '{prompt}'")

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
        
        logging.info(f"Invoking model '{model_id}'...")
        
        response = bedrock_client.invoke_model(
            body=body,
            modelId=model_id,
            accept='application/json',
            contentType='application/json'
        )

        logging.info("Received response from Bedrock LLM. Reading body...")
        response_body = json.loads(response.get('body').read())
        logging.debug(f"Raw response body from Bedrock: {response_body}")
        
        if 'content' not in response_body or not response_body['content'] or 'text' not in response_body['content'][0]:
            logging.error("Unexpected response structure from Bedrock. Content field is missing or malformed.")
            return "Could not generate a quote. Unexpected LLM response."

        generated_quote = response_body['content'][0]['text']
        logging.info(f"Successfully generated quote: '{generated_quote}'")
        
        return generated_quote
        
    except ClientError as e:
        logging.error(f"AWS ClientError when invoking Bedrock LLM: {e}")
        traceback.print_exc()
        return "Could not generate a quote. An AWS client error occurred."
    except Exception as e:
        logging.error(f"Unhandled exception when invoking Bedrock LLM: {e}")
        traceback.print_exc()
        return "Could not generate a quote. The LLM is unavailable."

# --- End AWS LLM Integration ---

@app.route('/messages', methods=['GET', 'POST'])
def handle_quotes():
    """
    Handles both GET and POST requests for quotes.
    """
    logging.info(f"Received {request.method} request for /messages")
    if request.method == 'GET':
        try:
            logging.info("Scanning DynamoDB for quotes...")
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
            logging.info(f"Retrieved {len(quotes)} quotes from DynamoDB.")
            return jsonify(quotes), 200
        except Exception as e:
            logging.error(f"Error fetching quotes from DynamoDB: {e}")
            traceback.print_exc()
            return jsonify(error="Failed to retrieve quotes"), 500

    elif request.method == 'POST':
        logging.info("Processing POST request for new quote.")
        
        try:
            if not request.is_json:
                logging.warning("Request is not JSON. Returning 400.")
                return jsonify(error="Request must be JSON"), 400

            data = request.get_json()
            logging.debug(f"Received JSON payload: {data}")
            name = data.get('name')
            input1 = data.get('input1')
            input2 = data.get('input2')
            input3 = data.get('input3')

            if not all([name, input1, input2, input3]):
                logging.warning("Missing required fields in POST request. Returning 400.")
                return jsonify(error="All fields (name, input1, input2, input3) are required"), 400
            
            logging.info("Initiating LLM quote generation...")
            generated_quote = generate_quote_with_aws_llm(name, input1, input2, input3)
            
            quote_id = str(uuid.uuid4())
            current_timestamp = int(time.time())
            
            item = {
                'id': quote_id,
                'name': name,
                'quote': generated_quote,
                'timestamp': current_timestamp
            }
            
            logging.info(f"Attempting to store new quote in DynamoDB with ID '{quote_id}'...")
            table.put_item(Item=item)
            logging.info("Quote successfully stored in DynamoDB.")
            
            return jsonify(id=quote_id, name=name, quote=generated_quote, message="Quote generated and posted successfully"), 201
            
        except ClientError as e:
            logging.error(f"DynamoDB ClientError during quote POST request: {e}")
            traceback.print_exc()
            return jsonify(error="Failed to store quote due to DynamoDB error"), 500
        except Exception as e:
            logging.error(f"Unhandled exception during quote POST request: {e}")
            traceback.print_exc()
            return jsonify(error="Failed to generate or post quote"), 500
    
    logging.warning(f"Received unsupported method {request.method} for /messages. Returning 405.")
    return jsonify(error="Method Not Allowed"), 405


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
