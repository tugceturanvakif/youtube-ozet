from http.server import BaseHTTPRequestHandler
import json
import re
import requests
import os
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
            
            # Video ID çıkar
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', video_url)
            if not match:
                raise Exception("Geçersiz YouTube URL")
            
            video_id = match.group(1)
            print(f"Video ID: {video_id}")
            
            # Transcript al - TAM FONKSİYON
            transcript = self.get_youtube_transcript(video_id)
            print(f"Transcript uzunluğu: {len(transcript)}")
            
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
            print(f"Hata: {e}")
            error = {'success': False, 'error': str(e)}
            self.wfile.write(json.dumps(error, ensure_ascii=False).encode('utf-8'))
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def get_youtube_transcript(self, video_id):
        """YouTube transcript al - KOMPLE FONKSİYON"""
        print("📝 YouTube transcript alınıyor...")
        
        # Önce basit requests ile dene
        transcript = self.try_simple_transcript(video_id)
        if transcript and len(transcript) > 100:
            return transcript
        
        # Fallback
        return self.generate_dummy_transcript(video_id)
    
    def try_simple_transcript(self, video_id):
        """Basit requests ile transcript dene"""
        try:
            print("🔄 Basit requests ile deneniyor...")
            
            # YouTube otomatik caption URL'leri
            urls_to_try = [
                f"https://www.youtube.com/api/timedtext?lang=tr&v={video_id}",
                f"https://www.youtube.com/api/timedtext?lang=en&v={video_id}",
                f"https://www.youtube.com/api/timedtext?lang=tr&v={video_id}&kind=asr",
                f"https://www.youtube.com/api/timedtext?lang=en&v={video_id}&kind=asr"
            ]
            
            for url in urls_to_try:
                try:
                    response = requests.get(url, timeout=10, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    
                    if response.status_code == 200 and len(response.text) > 100:
                        transcript = self.parse_xml_transcript(response.text)
                        if transcript:
                            print("✅ Basit requests ile transcript alındı!")
                            return transcript
                except Exception as e:
                    print(f"URL hatası: {e}")
                    continue
            
            return None
            
        except Exception as e:
            print(f"⚠️ Basit requests hatası: {e}")
            return None
    
    def parse_xml_transcript(self, xml_content):
        """XML transcript'i parse et - TAM FONKSİYON"""
        try:
            root = ET.fromstring(xml_content)
            transcript_parts = []
            
            for text_elem in root.findall('.//text'):
                text = text_elem.text
                if text:
                    # HTML entities decode
                    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    text = text.replace('&quot;', '"').replace('&#39;', "'")
                    transcript_parts.append(text.strip())
            
            return ' '.join(transcript_parts)
            
        except Exception as e:
            print(f"⚠️ XML parse hatası: {e}")
            return None
    
    def generate_dummy_transcript(self, video_id):
        """Son çare: Test transcript"""
        return f"""
        Bu video için gerçek transcript alınamadı. Video ID: {video_id}. 
        Bu durum genellikle videonun altyazısının olmadığı veya özel ayarlar nedeniyle 
        erişilemediği anlamına gelir. Lütfen altyazılı bir video deneyin.
        Sistem test modunda çalışıyor ve genel bir açıklama oluşturuyor.
        """
    
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
        except Exception as e:
            print(f"Video info hatası: {e}")
        
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
        
        # Transcript'i kısalt (çok uzunsa)
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
- Gereksiz detayları çıkar, önemli bilgileri koru
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
                    else:
                        return f"Beklenmeyen response yapısı: {result}"
                else:
                    return f"Candidates bulunamadı: {result}"
            else:
                return f"Gemini API Hatası ({response.status_code}): {response.text}"
                
        except Exception as e:
            return f"Gemini API Hatası: {str(e)}"