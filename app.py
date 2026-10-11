import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Configuration from Railway Environment Variables ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
NINEROUTER_URL = os.environ.get('NINEROUTER_URL', 'http://localhost:20128')
NINEROUTER_API_KEY = os.environ.get('NINEROUTER_API_KEY')
MASTER_PROMPT = os.environ.get('MASTER_PROMPT', 'You are ExamAce...') # Paste your full prompt here as a Railway variable
TELEGRAM_API = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'

# --- In-memory state store (for the quiz session) ---
# For a single-user bot, this is sufficient. For multiple users, use a database.
user_states = {}

def get_user_state(chat_id):
    """Retrieve or initialize state for a user."""
    if chat_id not in user_states:
        user_states[chat_id] = {
            "history": [],  # Store recent messages for context
            "session_data": {} # Store quiz-specific state if needed
        }
    return user_states[chat_id]

def send_telegram_message(chat_id, text):
    """Send a message back to the Telegram user."""
    url = f'{TELEGRAM_API}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown' # Enables formatting for reports
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def telegram_webhook():
    """Main webhook endpoint for Telegram updates."""
    update = request.get_json()
    
    if 'message' in update:
        chat_id = update['message']['chat']['id']
        user_message = update['message'].get('text', '')
        
        if not user_message:
            return jsonify({'status': 'ok'})
        
        # Get user's state (for context history)
        state = get_user_state(chat_id)
        
        # Build messages for the LLM, including history and master prompt
        messages = [
            {"role": "system", "content": MASTER_PROMPT}
        ]
        # Add recent history for context
        messages.extend(state['history'][-10:]) # Keep last 10 messages
        messages.append({"role": "user", "content": user_message})
        
        # --- Call 9router ---
        try:
            headers = {
                'Authorization': f'Bearer {NINEROUTER_API_KEY}',
                'Content-Type': 'application/json'
            }
            payload = {
                "model": "gemini/gemini-1.5-flash-latest", # Or your preferred model
                "messages": messages,
                "stream": False
            }
            response = requests.post(
                f'{NINEROUTER_URL}/v1/chat/completions',
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            ai_reply = response.json()['choices'][0]['message']['content']
            
            # Update user history (for context)
            state['history'].append({"role": "user", "content": user_message})
            state['history'].append({"role": "assistant", "content": ai_reply})
            
            # Send reply back to Telegram
            send_telegram_message(chat_id, ai_reply)
            
        except Exception as e:
            error_msg = f"❌ Error from 9router: {str(e)}"
            send_telegram_message(chat_id, error_msg)
            print(f"Error: {e}")
    
    return jsonify({'status': 'ok'})

@app.route('/healthz', methods=['GET'])
def health_check():
    """Healthcheck endpoint for Railway."""
    return jsonify({'status': 'ok', 'storage': 'in-memory'})

if __name__ == '__main__':
    # Railway provides the PORT environment variable
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
