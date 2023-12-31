# YTAudioConverterAPI

## Description
YTAudioConverterAPI is a Flask-based API that allows you to convert YouTube videos into MP3 audio files. It utilizes the pytube, youtubesearchpython, youtube_dl, and pydub libraries to search for videos, extract audio, and convert it to MP3 format.

## Installation
1. Clone the repository: `git clone <https://github.com/liwa-dev/YTAudioConverterAPI.git>`
2. Navigate to the project directory: `cd YTAudioConverterAPI`
3. Install the required dependencies: `pip install -r requirements.txt`

## Usage
1. Start the Flask server: `python main.py`
2. Send a GET request to `/search` endpoint with the `q` parameter to search for YouTube videos.
3. Send a GET request to `/download` endpoint with the `video_url` parameter to convert a YouTube video into an MP3 audio file.
4. Access the converted audio file by sending a GET request to `/audios/<filename>` endpoint.

## API Endpoints
- `/search`: Searches for YouTube videos based on the provided query (`q` parameter).
- `/download`: Converts a YouTube video into an MP3 audio file. Requires the `video_url` parameter.
- `/audios/<filename>`: Retrieves the converted audio file.

## Contributing
Contributions are welcome! If you have any suggestions, bug reports, or feature requests, please open an issue or submit a pull request.

## License
This project is licensed under the [MIT License](LICENSE).
