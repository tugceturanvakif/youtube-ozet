from http.server import BaseHTTPRequestHandler
import json
import re
import requests
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            video_url = data.get('videoUrl')
            
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', video_url)
            if not match:
                raise Exception("Geçersiz YouTube URL")
            
            video_id = match.group(1)
            print(f"✅ Video ID: {video_id}")
            
            # Transcript al
            transcript = self.get_transcript_with_ytdlp(video_id)
            print(f"📄 Transcript uzunluğu: {len(transcript)} karakter")
            
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
            print(f"❌ Hata: {e}")
            error = {'success': False, 'error': str(e)}
            self.wfile.write(json.dumps(error, ensure_ascii=False).encode('utf-8'))
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def get_transcript_with_ytdlp(self, video_id):
        """yt-dlp ile transcript al - Vercel uyumlu"""
        try:
            print("🔄 yt-dlp ile transcript alınıyor...")
            
            # Temp directory oluştur
            with tempfile.TemporaryDirectory() as temp_dir:
                # yt-dlp komutunu hazırla
                cmd = [
                    'python', '-m', 'yt_dlp',
                    '--write-auto-sub',
                    '--sub-lang', 'tr,en',
                    '--skip-download',
                    '--sub-format', 'vtt',
                    '--output', f'{temp_dir}/%(id)s.%(ext)s',
                    f'https://www.youtube.com/watch?v={video_id}'
                ]
                
                # yt-dlp çalıştır
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    
                    if result.returncode == 0:
                        # VTT dosyasını bul ve oku
                        import glob
                        vtt_files = glob.glob(f'{temp_dir}/*.vtt')
                        
                        if vtt_files:
                            with open(vtt_files[0], 'r', encoding='utf-8') as f:
                                vtt_content = f.read()
                            
                            transcript = self.parse_vtt(vtt_content)
                            if transcript and len(transcript) > 100:
                                print("✅ yt-dlp ile transcript alındı!")
                                return transcript
                    else:
                        print(f"yt-dlp hatası: {result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    print("yt-dlp timeout")
                except Exception as e:
                    print(f"yt-dlp subprocess hatası: {e}")
            
            # Fallback
            return self.fallback_transcript(video_id)
            
        except Exception as e:
            print(f"yt-dlp genel hatası: {e}")
            return self.fallback_transcript(video_id)
    
    def parse_vtt(self, vtt_content):
        """VTT dosyasını parse et"""
        try:
            lines = vtt_content.split('\n')
            transcript_lines = []
            
            for line in lines:
                line = line.strip()
                if (line and 
                    not line.startswith('WEBVTT') and 
                    not '-->' in line and 
                    not line.startswith('NOTE') and
                    not line.isdigit() and
                    not line.startswith('<')):
                    
                    line = re.sub(r'<[^>]+>', '', line)
                    if line:
                        transcript_lines.append(line)
            
            return ' '.join(transcript_lines)
            
        except Exception as e:
            print(f"VTT parse hatası: {e}")
            return None
    
    def fallback_transcript(self, video_id):
        """Fallback: youtube-transcript-api"""
        try:
            print("🔄 Fallback: youtube-transcript-api...")
            from youtube_transcript_api import YouTubeTranscriptApi
            
            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['tr'])
                print("✅ Türkçe transcript bulundu!")
            except:
                try:
                    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
                    print("✅ İngilizce transcript bulundu!")
                except:
                    transcript = YouTubeTranscriptApi.get_transcript(video_id)
                    print("✅ Otomatik transcript bulundu!")
            
            return ' '.join([item['text'] for item in transcript])
            
        except Exception as e:
            print(f"Fallback hatası: {e}")
            return f"Bu video için transcript alınamadı. Video ID: {video_id}"
    
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
        print("🤖 Gemini API'ye istek gönderiliyor...")
        
        api_key = os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            return "⚠️ Gemini API key gerekli!"
        
        if len(transcript) > 15000:
            transcript = transcript[:15000] + "..."
            print("✂️ Transcript kısaltıldı")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        
        data = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"""Bu YouTube video metnini Türkçe olarak özetle. 

Özet kuralları:
- 4-5 paragraf halinde yaz
- Ana konuları ve önemli noktaları dahil et
- Net, anlaşılır ve akıcı Türkçe kullan
- Video izleyicisi için değerli olsun
- Sonunda 3-4 önemli çıkarımı bullet point (•) olarak ekle

Video metni:
{transcript}"""
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 1500,
            }
        }
        
        try:
            response = requests.post(url, json=data, timeout=90)
            
            print(f"📊 Gemini API Status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                
                if 'candidates' in result and len(result['candidates']) > 0:
                    if 'content' in result['candidates'][0] and 'parts' in result['candidates'][0]['content']:
                        summary = result['candidates'][0]['content']['parts'][0]['text']
                        print("✅ Gemini özet başarıyla alındı!")
                        return summary
            
            return f"Gemini API Hatası: {response.text}"
                
        except Exception as e:
            return f"Gemini API Hatası: {str(e)}"