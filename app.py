import boto3
import os
import uuid
import time
import json
import traceback
import logging

from flask import Flask, jsonify, request
from flask_cors import CORS
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

app = Flask(__name__)
CORS(app)

logging.info("Flask application starting up...")


# --- DynamoDB Initialization ---
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME',
                                     'ugp-eks-cicd-messages-table')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

logging.info(
    "Initializing DynamoDB resource for table '%s' in region '%s'...",
    DYNAMODB_TABLE_NAME, AWS_REGION
)
try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    logging.info("DynamoDB table '%s' resource initialized successfully.",
                 DYNAMODB_TABLE_NAME)
except Exception as e:
    logging.fatal(
        "Failed to initialize DynamoDB table '%s': %s",
        DYNAMODB_TABLE_NAME, e
    )
    # In a real-world scenario, you might want to exit the application here
    # to prevent further errors.
    pass


# --- AWS LLM Integration ---
def generate_quote_with_aws_llm(name, input1, input2, input3):
    """
    Generates a funny quote using Amazon Bedrock with the Anthropic Claude 3
    Sonnet model.
    """
    logging.info("Preparing to invoke AWS Bedrock LLM...")
    try:
        bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=AWS_REGION
        )
        logging.info("Bedrock client created successfully.")

        prompt = (
            f"You are a witty desi Gen Z roast master with perfect meme "
            f"timing. Write one short, hilarious roast (max 25 words) about "
            f"someone named {name}, involving {input1}, {input2}, and {input3}. "
            "Make it sound like a viral Instagram meme or reel caption — "
            "sarcastic, visual, and instantly relatable. The humor should be "
            "sharp but safe, like how friends roast each other in college "
            "group chats. No vulgarity, no adult jokes, no politics, no slurs. "
            "Use Hinglish. Only output the roast quote. Nothing else."
        )
        logging.info("Using prompt: '%s'", prompt)

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

        logging.info("Invoking model '%s'...", model_id)

        response = bedrock_client.invoke_model(
            body=body,
            modelId=model_id,
            accept='application/json',
            contentType='application/json'
        )

        logging.info("Received response from Bedrock LLM. Reading body...")
        response_body = json.loads(response.get('body').read())
        logging.debug("Raw response body from Bedrock: %s", response_body)

        if ('content' not in response_body or
                not response_body['content'] or
                'text' not in response_body['content'][0]):
            logging.error("Unexpected response structure from Bedrock. "
                          "Content field is missing or malformed.")
            return "Could not generate a quote. Unexpected LLM response."

        generated_quote = response_body['content'][0]['text']
        logging.info("Successfully generated quote: '%s'", generated_quote)

        return generated_quote

    except ClientError as e:
        logging.error("AWS ClientError when invoking Bedrock LLM: %s", e)
        traceback.print_exc()
        return "Could not generate a quote. An AWS client error occurred."
    except Exception as e:
        logging.error("Unhandled exception when invoking Bedrock LLM: %s", e)
        traceback.print_exc()
        return "Could not generate a quote. The LLM is unavailable."


@app.route('/messages', methods=['GET', 'POST'])
def handle_quotes():
    """
    Handles both GET and POST requests for quotes.
    """
    logging.info(f"Received {request.method} request for /messages")
    if request.method == 'GET':
        try:
            logging.info("Scanning DynamoDB for quotes...")
            # In a real app, you would want to use pagination
            # for large datasets
            response = table.scan(
                FilterExpression=Attr('quote').exists()
            )
            quotes = []
            sorted_items = sorted(response.get('Items', []),
                                  key=lambda x: x.get('timestamp', 0),
                                  reverse=True)

            for item in sorted_items:
                # Include the reactions field in the response
                quotes.append({
                    "id": item.get("id"),
                    "name": item.get("name", "Unknown"),
                    "quote": item.get("quote", "No quote provided"),
                    "reactions": item.get("reactions", {})
                })
            logging.info("Retrieved %s quotes from DynamoDB.", len(quotes))
            return jsonify(quotes), 200
        except Exception as e:
            logging.error("Error fetching quotes from DynamoDB: %s", e)
            traceback.print_exc()
            return jsonify(error="Failed to retrieve quotes"), 500

    elif request.method == 'POST':
        logging.info("Processing POST request for new quote.")

        try:
            if not request.is_json:
                logging.warning("Request is not JSON. Returning 400.")
                return jsonify(error="Request must be JSON"), 400

            data = request.get_json()
            logging.debug("Received JSON payload: %s", data)
            name = data.get('name')
            input1 = data.get('input1')
            input2 = data.get('input2')
            input3 = data.get('input3')

            if not all([name, input1, input2, input3]):
                logging.warning("Missing required fields in POST request. "
                                "Returning 400.")
                return jsonify(error="All fields (name, input1, input2, "
                                     "input3) are required"), 400

            logging.info("Initiating LLM quote generation...")
            generated_quote = generate_quote_with_aws_llm(
                name, input1, input2, input3)

            quote_id = str(uuid.uuid4())
            current_timestamp = int(time.time())

            item = {
                'id': quote_id,
                'name': name,
                'quote': generated_quote,
                'timestamp': current_timestamp,
                # Initialize all reaction counts to 0
                'reactions': {
                    'laugh': 0, 'love': 0, 'tears': 0, 'sad': 0, 'like': 0,
                    'downvote': 0, 'report': 0
                }
            }

            logging.info("Attempting to store new quote in DynamoDB with "
                         "ID '%s'...", quote_id)
            table.put_item(Item=item)
            logging.info("Quote successfully stored in DynamoDB.")

            return jsonify(
                id=quote_id,
                name=name,
                quote=generated_quote,
                message="Quote generated and posted successfully"
            ), 201

        except ClientError as e:
            logging.error(
                "DynamoDB ClientError during quote POST request: %s", e
            )
            traceback.print_exc()
            return jsonify(
                error="Failed to store quote due to DynamoDB error"
            ), 500
        except Exception as e:
            logging.error(
                "Unhandled exception during quote POST request: %s", e
            )
            traceback.print_exc()
            return jsonify(
                error="Failed to generate or post quote"
            ), 500

    logging.warning("Received unsupported method %s for /messages. "
                    "Returning 405.", request.method)
    return jsonify(error="Method Not Allowed"), 405


@app.route('/messages/<string:quote_id>/react', methods=['PUT', 'OPTIONS'])
def handle_react(quote_id):
    """
    Handles PUT requests to update a reaction count for a specific quote.
    Includes logic to automatically delete a quote if it receives more than
    10 reports.
    """
    logging.info("Received PUT request for /messages/%s/react", quote_id)

    if request.method == 'OPTIONS':
        # This block handles the preflight request explicitly, if needed.
        # However, the CORS(app) initialization should handle this.
        # This is a safe fallback to ensure the request succeeds.
        return '', 204

    try:
        if not request.is_json:
            logging.warning("Request is not JSON. Returning 400.")
            return jsonify(error="Request must be JSON"), 400

        data = request.get_json()
        reaction_name = data.get('reaction')

        if not reaction_name:
            logging.warning("Reaction name is missing. Returning 400.")
            return jsonify(error="Reaction name is required"), 400

        # --- FIX FOR BACKWARD COMPATIBILITY & AUTO-DELETE LOGIC ---
        # This new logic handles items that are missing the 'reactions' map.
        # It uses a two-step update to ensure the map exists before trying to
        # update a nested attribute within it.
        try:
            # First, try to increment the counter directly. This works for new
            # quotes or old quotes that already have the 'reactions' map.
            response = table.update_item(
                Key={'id': quote_id},
                UpdateExpression='ADD #reactions.#reaction_name :val',
                ConditionExpression='attribute_exists(#reactions)',
                ExpressionAttributeNames={
                    '#reactions': 'reactions',
                    '#reaction_name': reaction_name
                },
                ExpressionAttributeValues={
                    ':val': 1
                },
                ReturnValues='ALL_NEW'
            )
        except ClientError as e:
            # If the reactions map does not exist, the first update will fail
            # with a ConditionalCheckFailedException. This is where we handle
            # old items.
            if (e.response['Error']['Code'] ==
                    'ConditionalCheckFailedException'):
                logging.info(
                    "Reaction map missing for quote ID '%s', "
                    "attempting to create it...", quote_id)
                # Now, perform a second update that creates the 'reactions' map
                # and sets the first reaction count.
                response = table.update_item(
                    Key={'id': quote_id},
                    UpdateExpression='SET #reactions = :initial_map',
                    ConditionExpression='attribute_not_exists(#reactions)',
                    ExpressionAttributeNames={
                        '#reactions': 'reactions'
                    },
                    ExpressionAttributeValues={
                        ':initial_map': {reaction_name: 1}
                    },
                    ReturnValues='ALL_NEW'
                )
            else:
                # If the error is something else, re-raise it.
                raise e

        # --- AUTO-DELETE LOGIC: Check and delete if too many reports ---
        updated_attributes = response.get('Attributes', {})
        if (reaction_name == 'report' and
                updated_attributes.get('reactions', {}).get('report', 0) > 10):
            logging.info("Quote with ID '%s' received more than 10 reports. "
                         "Deleting...", quote_id)
            table.delete_item(Key={'id': quote_id})
            logging.info("Quote with ID '%s' successfully deleted from "
                         "DynamoDB.", quote_id)
            return jsonify(
                message=f"Quote {quote_id} deleted due to excessive reports"
            ), 200

        # --- END OF FIX ---

        logging.info("Successfully updated reaction '%s' for quote ID '%s'.",
                     reaction_name, quote_id)
        return jsonify(response['Attributes']), 200

    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            logging.error("Quote with ID '%s' not found.", quote_id)
            return jsonify(error="Quote not found"), 404
        else:
            logging.error(
                "DynamoDB ClientError during reaction update: %s", e
            )
            traceback.print_exc()
            return jsonify(
                error="Failed to update reaction due to DynamoDB error"
            ), 500
    except Exception as e:
        logging.error("Unhandled exception during reaction update: %s", e)
        traceback.print_exc()
        return jsonify(error="Failed to update reaction"), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
