from http.server import BaseHTTPRequestHandler
import json
import re
import requests
import os

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # CORS headers
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

            # Request body'yi oku
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            video_url = data.get('videoUrl')
            
            # Video ID çıkar
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', video_url)
            if not match:
                raise Exception("Geçersiz YouTube URL")
            
            video_id = match.group(1)
            
            # Transcript al (basit versiyon - Vercel için)
            transcript = self.get_simple_transcript(video_id)
            
            # Video bilgilerini al
            video_info = self.get_video_info(video_id)
            
            # Gemini ile özet yap
            summary = self.gemini_ozet_yap(transcript)
            
            response = {
                'success': True,
                'title': video_info['title'],
                'channel': video_info['channel'],
                'thumbnail': video_info['thumbnail'],
                'summary': summary
            }
            
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
            
        except Exception as e:
            error = {'success': False, 'error': str(e)}
            self.wfile.write(json.dumps(error, ensure_ascii=False).encode('utf-8'))
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS') 
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def get_simple_transcript(self, video_id):
        """Basit transcript alma - Vercel için optimize"""
        try:
            # YouTube otomatik caption URL dene
            urls = [
                f"https://www.youtube.com/api/timedtext?lang=tr&v={video_id}",
                f"https://www.youtube.com/api/timedtext?lang=en&v={video_id}"
            ]
            
            for url in urls:
                try:
                    response = requests.get(url, timeout=15, headers={
                        'User-Agent': 'Mozilla/5.0 (compatible; YouTubeBot/1.0)'
                    })
                    
                    if response.status_code == 200 and len(response.text) > 100:
                        transcript = self.parse_xml_transcript(response.text)
                        if transcript:
                            return transcript
                except:
                    continue
            
            # Fallback
            return f"Bu video için transcript alınamadı. Video ID: {video_id}. Lütfen altyazılı bir video deneyin."
            
        except Exception as e:
            return f"Transcript hatası: {str(e)}"
    
    def parse_xml_transcript(self, xml_content):
        """XML transcript parse et"""
        try:
            import xml.etree.ElementTree as ET
            
            root = ET.fromstring(xml_content)
            transcript_parts = []
            
            for text_elem in root.findall('.//text'):
                text = text_elem.text
                if text:
                    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    transcript_parts.append(text.strip())
            
            return ' '.join(transcript_parts)
            
        except:
            return None
    
    def get_video_info(self, video_id):
        """Video bilgilerini al"""
        try:
            url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'title': data.get('title', 'YouTube Video'),
                    'channel': data.get('author_name', 'YouTube Kanalı'),
                    'thumbnail': f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
                }
        except:
            pass
        
        return {
            'title': 'YouTube Video',
            'channel': 'YouTube Kanalı',
            'thumbnail': f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
        }
    
    def gemini_ozet_yap(self, transcript):
        """Gemini ile özet"""
        api_key = os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            return "Gemini API key bulunamadı. Lütfen environment variable ekleyin."
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        
        data = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"Bu YouTube video metnini Türkçe özetle:\n\n{transcript[:10000]}"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 1000,
            }
        }
        
        try:
            response = requests.post(url, json=data, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and len(result['candidates']) > 0:
                    return result['candidates'][0]['content']['parts'][0]['text']
            
            return f"Özet oluşturulamadı: {response.text}"
            
        except Exception as e:
            return f"Gemini API hatası: {str(e)}"