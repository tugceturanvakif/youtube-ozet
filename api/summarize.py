from http.server import BaseHTTPRequestHandler
import json
import re
import requests
import subprocess
import os
import xml.etree.ElementTree as ET
import tempfile
import glob

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

            # Video URL al
            content_length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            video_url = data.get('videoUrl')
            
            # Video ID çıkar
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', video_url)
            if not match:
                raise Exception("Geçersiz YouTube URL")
            
            video_id = match.group(1)
            print(f"✅ Video ID: {video_id}")
            
            # Gerçek transcript al
            transcript = self.get_youtube_transcript(video_id)
            print(f"📄 Transcript uzunluğu: {len(transcript)} karakter")
            
            # Video bilgilerini al (basit)
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
    
    def get_youtube_transcript(self, video_id):
        """Alternatif transcript yöntemleri"""
        print("📝 YouTube transcript alınıyor...")
        
        # Önce basit requests ile dene
        transcript = self.try_simple_transcript(video_id)
        if transcript and len(transcript) > 100:
            return transcript
        
        # Sonra yt-dlp dene (daha az agresif)
        transcript = self.try_ytdlp_transcript(video_id)
        if transcript and len(transcript) > 100:
            return transcript
        
        # Son olarak fallback
        return self.fallback_transcript(video_id)
    
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
                except:
                    continue
            
            return None
            
        except Exception as e:
            print(f"⚠️ Basit requests hatası: {e}")
            return None
    
    def parse_xml_transcript(self, xml_content):
        """XML transcript'i parse et"""
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
    
    def try_ytdlp_transcript(self, video_id):
        """yt-dlp ile transcript al (daha nazik)"""
        try:
            print("🔄 yt-dlp ile deneniyor (rate limit aware)...")
            
            # Temp dizin oluştur
            with tempfile.TemporaryDirectory() as temp_dir:
                # Daha nazik ayarlar
                cmd = [
                    'yt-dlp',
                    '--write-auto-sub',
                    '--sub-lang', 'tr',
                    '--skip-download',
                    '--sub-format', 'vtt',
                    '--sleep-interval', '2',  # 2 saniye bekle
                    '--max-sleep-interval', '5',  # Max 5 saniye
                    '--output', f'{temp_dir}/temp_%(id)s.%(ext)s',
                    f'https://www.youtube.com/watch?v={video_id}'
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                
                if result.returncode == 0:
                    # VTT dosyasını oku
                    vtt_files = glob.glob(f'{temp_dir}/temp_{video_id}*.vtt')
                    
                    if vtt_files:
                        vtt_file = vtt_files[0]
                        with open(vtt_file, 'r', encoding='utf-8') as f:
                            vtt_content = f.read()
                        
                        transcript = self.parse_vtt(vtt_content)
                        
                        print("✅ yt-dlp ile transcript alındı!")
                        return transcript
                else:
                    print(f"⚠️ yt-dlp hatası: {result.stderr}")
                
                return None
            
        except Exception as e:
            print(f"⚠️ yt-dlp hatası: {e}")
            return None
    
    def parse_vtt(self, vtt_content):
        """VTT dosyasını parse et"""
        lines = vtt_content.split('\n')
        transcript_lines = []
        
        for line in lines:
            line = line.strip()
            # Zaman damgası ve meta verileri atla
            if (line and 
                not line.startswith('WEBVTT') and 
                not '-->' in line and 
                not line.startswith('NOTE') and
                not line.isdigit() and
                not line.startswith('<')):
                
                # HTML etiketlerini temizle
                line = re.sub(r'<[^>]+>', '', line)
                if line:
                    transcript_lines.append(line)
        
        return ' '.join(transcript_lines)
    
    def fallback_transcript(self, video_id):
        """Fallback: youtube-transcript-api kullan"""
        try:
            print("🔄 Fallback: youtube-transcript-api deneniyor...")
            
            # youtube-transcript-api'yi import etmeye çalış
            from youtube_transcript_api import YouTubeTranscriptApi
            
            # Önce Türkçe dene
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
            
        except ImportError:
            print("❌ youtube-transcript-api kütüphanesi yok")
            return self.generate_dummy_transcript(video_id)
        except Exception as e:
            print(f"❌ Fallback hatası: {e}")
            return self.generate_dummy_transcript(video_id)
    
    def generate_dummy_transcript(self, video_id):
        """Son çare: Dummy transcript"""
        return f"""
        Bu bir örnek video içeriğidir. Video ID: {video_id}. 
        Video içeriği hakkında gerçek transcript alınamadı. 
        Bu durumda sistem otomatik olarak genel bir açıklama oluşturuyor.
        Lütfen altyazılı bir video deneyin veya transcript API'lerini kontrol edin.
        """
    
    def get_video_info(self, video_id):
        """Video bilgilerini al"""
        try:
            # YouTube oEmbed API kullan (key gerektirmez)
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
        
        # Fallback
        return {
            'title': 'YouTube Video',
            'channel': 'YouTube Kanalı',
            'thumbnail': f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
        }
    
    def gemini_ozet_yap(self, transcript):
        """Google Gemini ile özet yap"""
        print("🤖 Gemini API'ye istek gönderiliyor...")
        
        # Environment variable'dan API key al
        api_key = os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            return "⚠️ Gemini API key gerekli! Lütfen environment variable ekleyin."
        
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