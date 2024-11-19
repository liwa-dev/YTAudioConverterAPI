import os
import re
import uuid
import time
import json
import threading
import requests
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context, make_response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pytube import YouTube as YT
from youtubesearchpython import VideosSearch
import yt_dlp
from pydub import AudioSegment
from dotenv import load_dotenv
import logging
from urllib.parse import urlparse

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configure CORS
allowed_origins = os.getenv('ALLOWED_ORIGINS', '').split(',')
cors = CORS(app, resources={r"/*": {"origins": allowed_origins}})

# Define the retention period in seconds (e.g., 24 hours)
RETENTION_PERIOD = int(os.getenv('RETENTION_PERIOD', 2 * 60 * 60))

# Configure rate limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["30 per second"],
    storage_uri="memory://",
)

@app.route('/')
def nothing():
    response = jsonify({'msg': 'Use /download or /mp3/<filename>'})
    response.headers.add('Content-Type', 'application/json')
    return response

def compress_audio(file_path):
    if not os.path.exists(file_path):
        logger.warning(f"File {file_path} does not exist. Skipping compression.")
        return
    try:
        audio = AudioSegment.from_file(file_path)
        compressed_audio = audio.export(file_path, format='mp3', bitrate='128k')
        compressed_audio.close()
    except Exception as e:
        logger.error(f"Error compressing audio: {str(e)}")

def generate(host_url, video_url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'mp3/%(id)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
            'nopostoverwrites': True
        }],
        'verbose': True,
        'ffmpeg_args': ['-threads', '4'],
    }

    cookies_path = os.path.join(os.getcwd(), 'cookies.txt')
    if os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path
    else:
        logger.warning("Warning: cookies.txt not found. Proceeding without cookies.")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=False)
            video_id = info_dict.get('id')
            
            file_name = f"{video_id}.mp3"
            file_path = os.path.join('mp3', file_name)
            
            if os.path.exists(file_path):
                logger.info(f"File {file_path} already exists. Skipping download.")
            else:
                info_dict = ydl.extract_info(video_url, download=True)
                audio_file_path = ydl.prepare_filename(info_dict)
                compress_audio(file_path)
            
            thumbnail_url = info_dict.get('thumbnail')
            expiration_timestamp = int(time.time()) + RETENTION_PERIOD
            
            # Fire webhook
            webhook_url = os.getenv('WEBHOOK_URL')
            webhook_data = {
                "status": "complete",
                "file_name": file_name,
                "expiration_timestamp": expiration_timestamp
            }
            try:
                requests.post(webhook_url, json=webhook_data)
            except requests.RequestException as e:
                logger.error(f"Failed to send webhook: {str(e)}")

            response_dict = {
                'img': thumbnail_url,
                'direct_link': f"{os.getenv('BASE_URL', 'https://example.com')}/mp3/{file_name}",
                'expiration_timestamp': expiration_timestamp
            }
            response_json = json.dumps(response_dict)
            response_bytes = response_json.encode('utf-8')
            with app.app_context():
                yield response_bytes
    except Exception as e:
        logger.error(f"Error in generate function: {str(e)}")
        yield json.dumps({"error": "An error occurred during processing"}).encode('utf-8')

@app.route('/search', methods=['GET'])
@limiter.limit("5/minute", error_message="Too many requests")
def search():
    q = request.args.get('q')
    if q is None or len(q.strip()) == 0:
        return jsonify({'error': 'Invalid search query'}), 400
    try:
        s = VideosSearch(q, limit=15)
        results = s.result()["result"]
        search_results = [{'title': video["title"], 'url': video["link"], 'thumbnail': video["thumbnails"][0]["url"]} for video in results]
        response = jsonify({'search': search_results})
        response.headers.add('Content-Type', 'application/json')
        return response
    except Exception as e:
        logger.error(f"Error in search function: {str(e)}")
        return jsonify({'error': 'An error occurred during search'}), 500

@app.route('/download', methods=['GET'])
@limiter.limit("5/minute", error_message="Too many requests")
def download_audio():
    api_key = request.headers.get('x-key')
    if api_key != os.getenv('API_KEY'):
        return jsonify({'error': 'Invalid or missing key header'}), 403

    video_url = request.args.get('video_url')
    if not video_url or not urlparse(video_url).scheme:
        return jsonify({'error': 'Invalid or missing video URL'}), 400

    host_url = request.base_url + '/'
    return Response(stream_with_context(generate(host_url, video_url)), mimetype='application/json')

@app.route('/mp3/<path:filename>', methods=['GET'])
@limiter.limit("2/5seconds", error_message="Too many requests")
def serve_audio(filename):
    root_dir = os.getcwd()
    file_path = os.path.join(root_dir, 'mp3', filename)
    
    if not os.path.isfile(file_path) or not filename.endswith('.mp3'):
        return make_response('Audio file not found', 404)
    
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get('Range')
    
    if range_header:
        start_pos, end_pos = parse_range_header(range_header, file_size)
        response = make_partial_response(file_path, start_pos, end_pos, file_size)
    else:
        response = make_entire_response(file_path, file_size)
    
    response.headers.set('Access-Control-Allow-Origin', ', '.join(allowed_origins))
    response.headers.set('Access-Control-Allow-Methods', 'GET')
    response.headers.set('Content-Type', 'audio/mpeg')
    response.headers.set('X-Content-Type-Options', 'nosniff')
    response.headers.set('Content-Security-Policy', "default-src 'self'")
    
    return response

def parse_range_header(range_header, file_size):
    range_match = re.search(r'(\d+)-(\d*)', range_header)
    start_pos = int(range_match.group(1)) if range_match.group(1) else 0
    end_pos = int(range_match.group(2)) if range_match.group(2) else file_size - 1
    return start_pos, end_pos

def make_partial_response(file_path, start_pos, end_pos, file_size):
    with open(file_path, 'rb') as file:
        file.seek(start_pos)
        content_length = end_pos - start_pos + 1
        content = file.read(content_length)
    
    response = make_response(content)
    response.headers.set('Content-Range', f'bytes {start_pos}-{end_pos}/{file_size}')
    response.headers.set('Content-Length', str(content_length))
    response.status_code = 206
    return response

def make_entire_response(file_path, file_size):
    with open(file_path, 'rb') as file:
        content = file.read()
    
    response = make_response(content)
    response.headers.set('Content-Length', str(file_size))
    return response

def delete_expired_files():
    current_timestamp = int(time.time())
    for file_name in os.listdir('mp3'):
        file_path = os.path.join('mp3', file_name)
        if (os.path.isfile(file_path) and
                current_timestamp > os.path.getmtime(file_path) + RETENTION_PERIOD):
            try:
                os.remove(file_path)
                logger.info(f"Deleted expired file: {file_path}")
            except Exception as e:
                logger.error(f"Error deleting file {file_path}: {str(e)}")

def delete_files_task():
    delete_expired_files()
    threading.Timer(3600, delete_files_task).start()  # Run every hour

def run():
    app.run(host='127.0.0.1', port=5000)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

if __name__ == '__main__':
    delete_files_task()
    keep_alive()
