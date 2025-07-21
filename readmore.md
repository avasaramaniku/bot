# Instagram DM Automation Bot

This project implements a Flask-based webhook handler to automate direct messages (DMs) and private replies to comments on Instagram. It's designed to be robust, support multiple Instagram accounts, and provide smart, conditional responses.

## Features

-   **Multi-Instagram Account Support:** Manages DMs and comments for multiple distinct Instagram Business/Creator accounts from a single bot instance.
-   **Real-time Webhook Integration:** Actively listens for Instagram events (DMs, comments, mentions) via Meta's webhooks, including secure verification.
-   **Intelligent Input Processing & Data Storage:**
    * Detects and processes incoming Direct Messages (DMs).
    * Detects and processes new comments on Instagram Reels, posts, and live videos.
    * Automatically identifies existing users or creates new user profiles (with PSIDs/Instagram IDs, usernames, and interaction timestamps) in an SQLite database.
    * Maintains a detailed log of all incoming/outgoing messages and comments.
-   **Sophisticated Conditional Response Logic (for Comments):**
    * Responds to incoming DMs based on predefined keywords.
    * **Per-Reel Keyword Recognition:** Comments are analyzed against keywords specific to the `media_id` (Reel/Post ID) they were made on, configured in `reel_keywords.json`, with a `DEFAULT_KEYWORDS` fallback.
    * **Follower-Gated DM Content:**
        * **For Followers:** If a user commenting with a keyword is a follower, the bot sends a private DM with the requested link/information.
        * **For Non-Followers:** If a user commenting with a keyword is NOT a follower, the bot sends a *different* private DM (e.g., "Please follow our page to get the link!") to guide them.

## Setup & Deployment

### 1. Initial Setup & Prerequisites

1.  **Meta for Developers App Setup:**
    * Go to [https://developers.facebook.com/](https://developers.facebook.com/) and create a new "Business" app.
    * Add the "Messenger" product to your app.
    * Under "Messenger" -> "Instagram Settings", link each of your Instagram Business/Creator accounts (each must be linked to a unique Facebook Page).
    * For each linked account, note down its **Facebook Page ID** and generate/copy its **Page Access Token**.
    * Choose a unique, strong **`VERIFY_TOKEN`** of your own.
    * **Permissions Check:** Ensure your Meta App has the following permissions granted: `instagram_basic`, `pages_show_list`, `instagram_manage_messages`.

2.  **Python & Virtual Environment:**
    * Ensure Python 3 (e.g., 3.9+) is installed on your system.
    * Navigate to your project directory (`instagram_dm_bot/`) in your terminal/PowerShell.
    * Create a virtual environment: `python -m venv venv`
    * Activate it:
        * Linux/macOS: `source venv/bin/activate`
        * Windows PowerShell: `.\venv\Scripts\Activate`
        * Windows Command Prompt: `venv\Scripts\activate.bat`

3.  **Install Dependencies:**
    * With your virtual environment activated, install the required packages: `pip install -r requirements.txt`

4.  **Configure `.env`:**
    * Edit the `.env` file in your project root with your actual `VERIFY_TOKEN`, `IG_ACCOUNT_X_PAGE_ID`, and `IG_ACCOUNT_X_PAGE_ACCESS_TOKEN` values.

5.  **Configure `reel_keywords.json`:**
    * Edit `reel_keywords.json` to define your specific Reel `media_id`s, their keywords, and the `private_reply_message` for each. Remember to replace placeholder links.

### 2. Local Testing (Highly Recommended Before Deployment)

1.  **Start your Flask app:**
    * Open your terminal/PowerShell, navigate to `instagram_dm_bot/`, activate your virtual environment, and run: `python app.py`
    * Your app should start on `http://127.0.0.1:5000`.
2.  **Start `ngrok`:**
    * Open a *new* terminal/PowerShell window (keep the Flask app running).
    * Navigate to your `ngrok` executable's directory.
    * Run: `./ngrok http 5000` (or `ngrok http 5000`).
    * `ngrok` will provide a public HTTPS URL (e.g., `https://randomstring.ngrok-free.app`).
3.  **Update Meta Webhook URL (for local testing):**
    * Go to your Meta Developer App Dashboard -> "Messenger" -> "Webhooks".
    * Click "Edit Callback URL".
    * Set the "Callback URL" to your `ngrok` HTTPS URL followed by `/webhook` (e.g., `https://randomstring.ngrok-free.app/webhook`).
    * Enter your `VERIFY_TOKEN`.
    * Click "Verify and Save".
    * Ensure you are subscribed to the `messages` and `comments` fields under "Webhook Fields" for your Instagram account.
4.  **Test Functionality:**
    * **Direct DM:** From a test Instagram account, send a DM to one of your linked Instagram Business accounts (e.g., "hello", "help"). Check for automated replies.
    * **Reel Comment (Follower):** From a test Instagram account that *follows* your linked Instagram Business account, comment on a configured Reel with a keyword (e.g., "guide"). Check for the expected private DM.
    * **Reel Comment (Non-Follower):** From a test Instagram account that *does NOT follow* your linked Instagram Business account, comment on a configured Reel with a keyword. Check for the "Please follow..." private DM.
    * Monitor your Flask app's terminal for logs and errors.

### 3. Deployment to PythonAnywhere

Once local testing is successful:

1.  **Sign Up for PythonAnywhere:** Go to [https://www.pythonanywhere.com/](https://www.pythonanywhere.com/) and create a free "Beginner" account. Remember your username.
2.  **Upload Project Files:**
    * Log in to PythonAnywhere.
    * Go to the "Files" tab.
    * Create a new directory (e.g., `/home/yourusername/instagram_dm_bot`).
    * Upload `app.py`, `requirements.txt`, and `reel_keywords.json` to this new directory. **Do NOT upload your `.env` file.**
3.  **Configure Web App:**
    * Go to the "Web" tab.
    * Click "Add a new web app".
    * Accept the default domain (`yourusername.pythonanywhere.com`).
    * Choose "Flask" as the framework.
    * Select your Python version (e.g., "Python 3.10").
    * Set the "Code location" to the full path of your project directory (e.g., `/home/yourusername/instagram_dm_bot`).
4.  **Set up Virtual Environment & Install Dependencies:**
    * On your Web app configuration page, find the "Virtualenv" section.
    * Click the blue "Create" button next to the suggested path (e.g., `/home/yourusername/.virtualenvs/yourusername.pythonanywhere.com`).
    * Once created, open a "Bash console" from your Web tab (there's a link "Open Bash console here").
    * Activate your virtual environment in the console: `source /home/yourusername/.virtualenvs/yourusername.pythonanywhere.com/bin/activate` (adjust path if you chose a different one).
    * Install requirements: `pip install -r requirements.txt`
    * Close the console.
5.  **Configure WSGI File:**
    * On the "Web" tab, scroll down to the "Code" section.
    * Click the path next to "WSGI configuration file" (e.g., `/var/www/yourusername_pythonanywhere_com_wsgi.py`).
    * **Delete all existing content** in the editor.
    * **Paste the following code**, making sure to **replace `yourusername` and `instagram_dm_bot`** with your actual PythonAnywhere username and project folder name:
        ```python
        import sys
        import os

        # Add your project directory to the Python path
        project_home = '/home/yourusername/instagram_dm_bot'
        if project_home not in sys.path:
            sys.path.insert(0, project_home)

        # Import your Flask app. 'application' is the standard name for WSGI.
        from app import app as application
        ```
    * Click the **"Save"** button in the editor.
6.  **Set Environment Variables on PythonAnywhere:**
    * On the "Web" tab, scroll down to the "Environment variables" section.
    * Click "Add new environment variable" for each of your `.env` entries:
        * **Name:** `VERIFY_TOKEN`, **Value:** `YOUR_UNIQUE_AND_SECRET_VERIFY_TOKEN_HERE`
        * **Name:** `IG_ACCOUNT_1_PAGE_ID`, **Value:** `YOUR_FACEBOOK_PAGE_ID_FOR_ACCOUNT_1`
        * **Name:** `IG_ACCOUNT_1_PAGE_ACCESS_TOKEN`, **Value:** `YOUR_PAGE_ACCESS_TOKEN_FOR_ACCOUNT_1`
        * ...and so on for any other `IG_ACCOUNT_X` pairs.
7.  **Reload Your Web App:**
    * Scroll to the top of the "Web" tab.
    * Click the big green **"Reload yourusername.pythonanywhere.com"** button. This will apply all changes and start your bot.
8.  **Update Meta Webhook URL (for deployment):**
    * Go back to your Meta Developer App Dashboard -> "Messenger" -> "Webhooks".
    * Click "Edit Callback URL".
    * Set the "Callback URL" to your **PythonAnywhere domain** followed by `/webhook` (e.g., `https://yourusername.pythonanywhere.com/webhook`).
    * Ensure your `VERIFY_TOKEN` matches the one you set on PythonAnywhere.
    * Click "Verify and Save".
    * Confirm your Instagram account is subscribed to the `messages` and `comments` webhook fields.

## Usage

-   **Direct Messages:** Send a DM to any of your linked Instagram Business/Creator accounts. The bot will respond based on keywords defined in `app.py`.
-   **Reel/Post Comments:** Comment on one of your Reels or posts using keywords configured in `reel_keywords.json`. The bot will send a private DM to your comment, conditionally based on whether you are a follower or not.

---

This detailed breakdown should provide you with everything you need to set up and deploy your bot. Take your time with each step, and let me know if any part is unclear or if you encounter any issues!