import os
import requests
import json
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file.
# This must be called at the very beginning to ensure variables are available.
load_dotenv()

# --- Configuration (loaded from environment variables) ---
# Your unique, secret token used for webhook verification.
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
if not VERIFY_TOKEN:
    print("WARNING: VERIFY_TOKEN environment variable not set. Webhook verification will fail.")

# Initialize an empty list to store configurations for multiple Instagram accounts.
# Each dictionary in this list will contain the page_id and its corresponding access token.
INSTAGRAM_ACCOUNTS_CONFIG = []

# Loop to load multiple Instagram account configurations.
# This assumes your environment variables are named sequentially (e.g., IG_ACCOUNT_1_PAGE_ID, IG_ACCOUNT_2_PAGE_ID).
# Adjust the range (e.g., `range(1, 11)`) based on the maximum number of accounts you plan to support.
for i in range(1, 11):
    page_id_env_name = f"IG_ACCOUNT_{i}_PAGE_ID"
    page_access_token_env_name = f"IG_ACCOUNT_{i}_PAGE_ACCESS_TOKEN"

    page_id = os.environ.get(page_id_env_name)
    page_access_token = os.environ.get(page_access_token_env_name)

    if page_id and page_access_token:
        INSTAGRAM_ACCOUNTS_CONFIG.append({
            "page_id": page_id,
            "page_access_token": page_access_token
        })
    elif page_id or page_access_token: # Warn if one part of a pair is missing.
        print(f"WARNING: Incomplete configuration for {page_id_env_name} or {page_access_token_env_name}. Both must be set to activate this account.")
    else:
        # If we don't find the current account in sequence, assume no more accounts are configured.
        if i == 1 and not INSTAGRAM_ACCOUNTS_CONFIG:
            print("ERROR: No Instagram account configurations found. Please ensure IG_ACCOUNT_1_PAGE_ID and IG_ACCOUNT_1_PAGE_ACCESS_TOKEN are set.")
        break # Stop iterating if a sequential account number is not found.

# Load reel keywords from JSON file.
# This dictionary will store media_id -> {keywords: [], private_reply_message: ""} mappings.
REEL_KEYWORDS = {}
try:
    with open('reel_keywords.json', 'r') as f:
        REEL_KEYWORDS = json.load(f)
    print("Reel keywords loaded successfully from reel_keywords.json.")
    # Basic validation for REEL_KEYWORDS structure.
    if not isinstance(REEL_KEYWORDS, dict):
        print("WARNING: 'reel_keywords.json' might not be in the expected format (top-level must be a dictionary).")
except FileNotFoundError:
    print("ERROR: 'reel_keywords.json' not found. Auto-reply for comments will not work.")
except json.JSONDecodeError:
    print("ERROR: Invalid JSON in 'reel_keywords.json'. Auto-reply for comments will not work.")
except Exception as e:
    print(f"An unexpected error occurred while loading 'reel_keywords.json': {e}")


# --- Flask App Setup ---
# Initialize the Flask application.
app = Flask(__name__)

# --- Database Configuration (SQLite) ---
# Configure SQLAlchemy to use a SQLite database file named 'instagram_bot.db'.
# 'SQLALCHEMY_TRACK_MODIFICATIONS' is set to False to suppress a warning.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instagram_bot.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Database Models ---
# Define the User model to store information about Instagram users interacting with the bot.
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Page-Scoped ID (PSID) for direct messages, unique to your Facebook Page.
    psid = db.Column(db.String(100), unique=True, nullable=True, index=True)
    # Instagram User ID for comments and mentions, unique across Instagram.
    instagram_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    instagram_username = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_interaction_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Placeholder for future conversation flow management.
    conversation_state = db.Column(db.String(50), default='idle')

    # Define relationships with Message and Comment models.
    messages = db.relationship('Message', backref='user', lazy=True)
    comments = db.relationship('Comment', backref='user', lazy=True)

    def __repr__(self):
        return f"<User {self.instagram_username or self.psid or self.id}>"

# Define the Message model to log all incoming and outgoing direct messages.
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Link to the User who sent/received the message. Nullable for system events or if user is unknown.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # e.g., 'inbound_dm', 'outbound_dm', 'inbound_postback', 'private_reply_comment'.
    message_type = db.Column(db.String(50), nullable=False)
    message_text = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # Stores the original JSON payload for debugging/analysis.
    raw_payload = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Message {self.id} ({self.message_type})>"

# Define the Comment model to log all detected Instagram comments.
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # Instagram's unique ID for the comment itself.
    comment_id = db.Column(db.String(100), unique=True, nullable=False)
    # The ID of the Reel/Post the comment was made on.
    media_id = db.Column(db.String(100), nullable=False)
    comment_text = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # Stores the original JSON payload.
    raw_payload = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Comment {self.comment_id} on Media {self.media_id}>"

# --- Database Initialization ---
# This block ensures that all defined database tables are created when the Flask application starts.
# It uses app.app_context() to operate within the Flask application context.
with app.app_context():
    db.create_all()
    print("Database tables created or already exist.")

# --- Helper Functions for Instagram Graph API Interaction ---

def send_instagram_message(recipient_psid, message_text, page_id_for_sending, access_token_for_sending):
    """
    Sends a text message to an Instagram user's direct message inbox.
    This function dynamically uses the page_id and access_token corresponding to the
    Instagram account that received the original message/comment.
    """
    print(f"Attempting to send DM to PSID {recipient_psid} from Page {page_id_for_sending}: '{message_text}'")
    url = f"https://graph.facebook.com/v19.0/{page_id_for_sending}/messages"
    headers = {"Content-Type": "application/json"}
    params = {"access_token": access_token_for_sending}

    data = {
        "recipient": {"id": recipient_psid},
        "message": {"text": message_text}
    }

    try:
        response = requests.post(url, headers=headers, params=params, json=data)
        response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
        response_json = response.json()
        print(f"DM sent successfully! Response: {response_json}")

        # Log the outbound message to the database.
        with app.app_context():
            user = User.query.filter_by(psid=recipient_psid).first()
            if user:
                new_message = Message(
                    user_id=user.id,
                    message_type='outbound_dm',
                    message_text=message_text,
                    raw_payload=json.dumps(data)
                )
                db.session.add(new_message)
                db.session.commit()
            else:
                print(f"Warning: User with PSID {recipient_psid} not found when storing outbound DM.")

    except requests.exceptions.RequestException as e:
        print(f"Error sending DM: {e}")
        if response is not None:
            print(f"Response status code: {response.status_code}, content: {response.text}")

def send_instagram_private_reply_to_comment(comment_id, message_text, access_token_for_sending):
    """
    Sends a private message to a user who commented on a post/Reel.
    This DM appears linked to the original comment in the user's Instagram inbox.
    Requires 'instagram_manage_messages' permission for your Meta App.
    """
    print(f"Attempting to send PRIVATE reply to comment ID {comment_id}: '{message_text}'")
    url = f"https://graph.facebook.com/v19.0/{comment_id}/private_replies"
    headers = {"Content-Type": "application/json"}
    params = {"access_token": access_token_for_sending}

    data = {
        "message": message_text
    }

    try:
        response = requests.post(url, headers=headers, params=params, json=data)
        response.raise_for_status()
        response_json = response.json()
        print(f"Private reply sent successfully! Response: {response_json}")

        # Log the private reply message to the database.
        # Note: User association might be indirect here, as comment webhooks don't always provide PSID directly.
        with app.app_context():
             new_message = Message(
                 message_type='private_reply_comment',
                 message_text=message_text,
                 raw_payload=json.dumps(data)
             )
             db.session.add(new_message)
             db.session.commit()

    except requests.exceptions.RequestException as e:
        print(f"Error sending private reply: {e}")
        if response is not None:
            print(f"Response status code: {response.status_code}, content: {response.text}")

def check_if_user_follows_page(instagram_user_id, page_access_token):
    """
    Checks if a given Instagram user ID follows the Instagram Business Account
    associated with the provided page_access_token.
    Requires 'instagram_basic' and 'pages_show_list' permissions for your Meta App.
    """
    print(f"Checking follower status for Instagram User ID: {instagram_user_id}")
    
    # --- IMPORTANT NOTE ON FOLLOWER CHECK ---
    # The Meta Graph API does not provide a simple, direct boolean field
    # (like `is_following: true/false`) for checking if a specific Instagram user
    # follows a specific Instagram Business Account.
    #
    # The common approach involves:
    # 1. Getting the Instagram Business Account ID associated with your Page.
    # 2. Querying the `followers` edge of *your* Instagram Business Account,
    #    and then iterating through the (potentially large and paginated) list
    #    to see if the `instagram_user_id` is present. This is inefficient for real-time.
    #
    # Due to these complexities and potential rate limits/performance issues for a simple bot,
    # this function is currently a placeholder that always returns True.
    # For a production-grade bot with strict follower-gating, you would need to:
    # a) Implement the full pagination and search logic for the `followers` edge.
    # b) Potentially use a more advanced API (if Meta introduces one) or a third-party service.
    # c) Re-evaluate if the follower check is strictly necessary for every comment,
    #    or if a "follow to get link" message is sufficient for non-followers.
    #
    # For this project, we are proceeding with the logic that if a keyword is found,
    # we attempt to send a DM, and if `check_if_user_follows_page` returns False,
    # a different DM is sent. The current `return True` means the "follower" path is always taken.
    # To test the "non-follower" path, you can temporarily change `return True` to `return False`.
    # ----------------------------------------

    print(f"NOTE: 'check_if_user_follows_page' currently returns True as a placeholder.")
    print(f"For production, implement robust follower check via Meta Graph API or adjust logic.")
    return True # Placeholder: Assume user follows for demonstration. Change to False to test non-follower path.

# --- Flask Routes ---

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    """
    Handles webhook verification requests from Meta.
    Meta sends a GET request to verify the webhook URL.
    """
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if not all([mode, token, challenge]):
        print("WEBHOOK_VERIFICATION_FAILED: Missing parameters.")
        return 'Missing parameters', 400

    if mode == 'subscribe' and token == VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED successfully.")
        return challenge, 200
    else:
        print("WEBHOOK_VERIFICATION_FAILED: Invalid token or mode.")
        return 'Verification token mismatch', 403

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """
    Handles incoming webhook events from Meta (Instagram messages, comments, etc.).
    """
    data = request.json
    print(f"Received webhook data: {json.dumps(data, indent=2)}")

    # Basic validation for webhook data structure.
    if not data or not data.get("entry"):
        print("Invalid webhook data: 'entry' field missing or data is empty.")
        return jsonify({"status": "error", "message": "Invalid webhook data"}), 400

    for entry in data["entry"]:
        # Determine the recipient Page ID for this specific webhook entry.
        # This is crucial for multi-account support to know which account received the event.
        recipient_page_id = None
        if entry.get("id"): # For some events, the page ID is directly in entry['id'].
            recipient_page_id = str(entry["id"])
        elif entry.get("messaging"): # For message events, recipient is in messaging[0]['recipient']['id'].
            if entry["messaging"] and entry["messaging"][0].get("recipient"):
                recipient_page_id = str(entry["messaging"][0]["recipient"]["id"])
        elif entry.get("changes"): # For comments/mentions, page_id is in changes[0]['value']['page_id'].
            if entry["changes"] and entry["changes"][0].get("value") and entry["changes"][0]["value"].get("page_id"):
                recipient_page_id = str(entry["changes"][0]["value"]["page_id"])

        if not recipient_page_id:
            print("ERROR: Could not determine recipient_page_id for this entry. Skipping this entry.")
            continue # Skip to the next entry if page ID cannot be determined.

        # Find the corresponding access token for the determined Page ID.
        current_page_config = None
        for account_config in INSTAGRAM_ACCOUNTS_CONFIG:
            if account_config["page_id"] == recipient_page_id:
                current_page_config = account_config
                break

        if not current_page_config:
            print(f"ERROR: No matching PAGE_ACCESS_TOKEN found for recipient PAGE_ID: {recipient_page_id}. Please ensure it's configured. Skipping this entry.")
            continue # Skip to the next entry if no matching config is found.

        current_page_access_token = current_page_config["page_access_token"]
        # Now 'current_page_access_token' holds the correct token for this incoming event.

        # --- Process Instagram Message Events (Direct Messages & Postbacks) ---
        if entry.get("messaging"):
            for messaging_event in entry["messaging"]:
                sender_psid = messaging_event["sender"]["id"] # Page-Scoped ID for the user.
                
                # Handle incoming direct messages (excluding echoes of our own messages).
                if messaging_event.get("message") and messaging_event["message"].get("text") and messaging_event["message"].get("is_echo") is not True:
                    message_text = messaging_event["message"]["text"]
                    message_timestamp = datetime.fromtimestamp(messaging_event["timestamp"] / 1000)
                    print(f"Received message from PSID {sender_psid} for Page {recipient_page_id}: '{message_text}'")
                    
                    with app.app_context():
                        # Find or create the user in the database.
                        user = User.query.filter_by(psid=sender_psid).first()
                        if not user:
                            user = User(psid=sender_psid, created_at=message_timestamp)
                            db.session.add(user)
                            db.session.commit()
                            print(f"New DM user created (PSID: {sender_psid}) for Page {recipient_page_id}.")
                        else:
                            user.last_interaction_at = message_timestamp
                            db.session.commit()

                        # Log the incoming message.
                        new_message = Message(
                            user_id=user.id,
                            message_type='inbound_dm',
                            message_text=message_text,
                            timestamp=message_timestamp,
                            raw_payload=json.dumps(messaging_event)
                        )
                        db.session.add(new_message)
                        db.session.commit()
                        print(f"Stored inbound DM from {user.instagram_username or user.psid}: '{message_text}'.")

                        # Respond to DMs based on keywords.
                        message_text_lower = message_text.lower()
                        response_message = "I'm a bot! I'm still learning. Try 'hello', 'help', or 'products'." # Default response
                        if "hello" in message_text_lower or "hi" in message_text_lower:
                            response_message = f"Hi there, {user.instagram_username or 'friend'}! How can I help you today?"
                        elif "help" in message_text_lower:
                            response_message = "I can help with common questions. Try asking about 'products' or 'support'."
                        elif "products" in message_text_lower:
                            response_message = "We offer a range of exciting products! Visit our website to learn more: example.com"

                        # Send the automated DM response using the correct access token.
                        send_instagram_message(sender_psid, response_message, recipient_page_id, current_page_access_token)
                
                # Handle Postback events (e.g., clicks on quick reply buttons).
                elif messaging_event.get("postback"):
                    payload = messaging_event["postback"]["payload"]
                    message_timestamp = datetime.fromtimestamp(messaging_event["timestamp"] / 1000)
                    print(f"Received postback from PSID {sender_psid} for Page {recipient_page_id}: {payload}")

                    with app.app_context():
                        user = User.query.filter_by(psid=sender_psid).first()
                        if user:
                            user.last_interaction_at = message_timestamp
                            db.session.commit()
                        else:
                            print(f"Warning: User with PSID {sender_psid} not found for postback on Page {recipient_page_id}.")

                        new_message = Message(
                            user_id=user.id if user else None,
                            message_type='inbound_postback',
                            message_text=f"POSTBACK: {payload}",
                            timestamp=message_timestamp,
                            raw_payload=json.dumps(messaging_event)
                        )
                        db.session.add(new_message)
                        db.session.commit()

                        # Send a response to the postback.
                        send_instagram_message(sender_psid, f"You chose: {payload}. How else can I assist?", recipient_page_id, current_page_access_token)

        # --- Handle Changes (Comments, Mentions, etc.) ---
        elif entry.get("changes"):
            for change in entry["changes"]:
                field = change.get("field")
                value = change.get("value")

                # Process Instagram Comments (from Reels, Posts, Live videos).
                if field == "comments" and value:
                    comment_id = value.get("id") # The ID of the comment itself.
                    comment_text = value.get("text")
                    media_id = value.get("media", {}).get("id") # The ID of the Reel/Post.
                    media_type = value.get("media", {}).get("media_type")
                    sender_ig_id = value.get("from", {}).get("id") # The commenter's Instagram User ID.
                    sender_username = value.get("from", {}).get("username")
                    comment_timestamp = datetime.fromtimestamp(value.get("created_time") / 1000) # Assuming created_time is in ms

                    if comment_id and comment_text and sender_ig_id and media_id:
                        print(f"Detected comment from @{sender_username} (IG ID: {sender_ig_id}) on Media ID: {media_id} ({media_type}), Comment ID: {comment_id}: '{comment_text}' for Page {recipient_page_id}")

                        with app.app_context():
                            # Find or create the user in the database based on their Instagram ID.
                            user = User.query.filter_by(instagram_id=sender_ig_id).first()
                            if not user:
                                # If not found by IG ID, create new user. PSID might not be available here.
                                user = User(instagram_id=sender_ig_id, instagram_username=sender_username, created_at=comment_timestamp)
                                db.session.add(user)
                                db.session.commit()
                                print(f"New comment user created: {sender_username} (IG ID: {sender_ig_id}) for Page {recipient_page_id}.")
                            else:
                                user.last_interaction_at = comment_timestamp
                                if user.instagram_username != sender_username: # Update username if it changed.
                                    user.instagram_username = sender_username
                                db.session.commit()

                            # Log the incoming comment.
                            new_comment = Comment(
                                user_id=user.id,
                                comment_id=comment_id,
                                media_id=media_id,
                                comment_text=comment_text,
                                timestamp=comment_timestamp,
                                raw_payload=json.dumps(change)
                            )
                            db.session.add(new_comment)
                            db.session.commit()
                            print(f"Stored comment from {sender_username}.")

                            # --- Conditional DM Automation Logic for Comments ---
                            comment_text_lower = comment_text.lower()
                            
                            # Find matching reel configuration based on media_id
                            matched_reel_config = REEL_KEYWORDS.get(media_id)
                            
                            # If no specific config for this media_id, try to match against 'DEFAULT_KEYWORDS'
                            if not matched_reel_config:
                                default_keywords_config = REEL_KEYWORDS.get("DEFAULT_KEYWORDS", {})
                                for keyword in default_keywords_config.get("keywords", []):
                                    if keyword.lower() in comment_text_lower:
                                        matched_reel_config = default_keywords_config
                                        break
                                
                            if matched_reel_config and matched_reel_config.get("private_reply_message"):
                                # Perform Follower Check
                                is_follower = check_if_user_follows_page(sender_ig_id, current_page_access_token)

                                if is_follower:
                                    # If the user is a follower, send the requested content.
                                    dm_message = matched_reel_config["private_reply_message"]
                                    # You might want to customize this message to include the username.
                                    dm_message = dm_message.replace("{username}", sender_username)
                                    send_instagram_private_reply_to_comment(comment_id, dm_message, current_page_access_token)
                                    print(f"Sent private DM reply to @{sender_username} for comment ID {comment_id} (user IS a follower).")
                                else:
                                    # If the user is NOT a follower, send a different DM asking them to follow.
                                    non_follower_dm_message = f"Hi @{sender_username}, thanks for your comment! To get the link, please follow our page first. Once you follow, comment again or send us a DM, and we'll send it right over!"
                                    send_instagram_private_reply_to_comment(comment_id, non_follower_dm_message, current_page_access_token)
                                    print(f"User @{sender_username} (IG ID: {sender_ig_id}) is NOT following the page. Sent a private DM asking them to follow.")
                            else:
                                print(f"Comment from @{sender_username} did not contain a recognized keyword or no private_reply_message configured for Media ID {media_id} for Page {recipient_page_id}.")

                # Process Instagram Mentions (e.g., mentions in stories or other comments).
                elif field == "mentions" and value:
                    item = value.get("item")
                    if item and item.get("media_type") == "STORY":
                        story_id = item["id"]
                        sender_ig_id = value["user"]["id"]
                        sender_username = value["user"]["username"]
                        print(f"Detected story mention from @{sender_username} (IG ID: {sender_ig_id}) on story ID: {story_id} for Page {recipient_page_id}")
                        # You can add specific automation logic for story mentions here if needed.
                    elif item and item.get("media_type") in ["IMAGE", "VIDEO"]:
                        comment_id = item.get("id")
                        comment_text = value.get("text")
                        sender_ig_id = value["user"]["id"]
                        sender_username = value["user"]["username"]
                        print(f"Detected comment mention from @{sender_username} (IG ID: {sender_ig_id}) on comment ID: {comment_id}: '{comment_text}' for Page {recipient_page_id}")
                        # You can add specific automation logic for comment mentions here if needed.

    # Always return 200 OK to acknowledge receipt of the webhook event.
    return jsonify({"status": "ok"}), 200

# --- Health Check Route ---
@app.route('/')
def home():
    """A simple home route for health checking."""
    return "Instagram Bot is running!", 200

# --- Main entry point for Flask app ---
# This block is for local development only.
# When deploying to a production environment like PythonAnywhere, a WSGI server
# (like uWSGI which PythonAnywhere uses) will handle running the Flask application.
if __name__ == '__main__':
    # Print warnings if essential configurations are missing for local testing.
    if not VERIFY_TOKEN:
        print("WARNING: VERIFY_TOKEN is not set. Webhook verification will fail.")
    if not INSTAGRAM_ACCOUNTS_CONFIG:
        print("WARNING: No Instagram account configurations loaded. Ensure your .env is set up correctly.")
    if not REEL_KEYWORDS:
        print("WARNING: No reel keywords loaded. Comment automation will not function as expected.")

    # Run the Flask app in debug mode for local development.
    # On PythonAnywhere, this part is ignored.
    app.run(debug=True)