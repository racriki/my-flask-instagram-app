from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
from werkzeug.utils import secure_filename
import time
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from PIL import Image
import random
import requests
import logging

logging.basicConfig(level=logging.DEBUG)


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cake_uploader.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# 이미지 업로드 설정
UPLOAD_FOLDER = os.path.join('static', 'uploads')
MAX_IMAGE_SIZE = (1200, 1200)  # 인스타그램 최적화 크기
THUMBNAIL_SIZE = (300, 300)    # 썸네일 크기

# 디자인 이미지 경로 설정
DESIGN_PATHS = {
    'bts_character': os.path.join('static', 'uploads', 'designs', 'bts-character'),
    'jin_character': os.path.join('static', 'uploads', 'designs', 'jin-character'),
    'jin_photo': os.path.join('static', 'uploads', 'designs', 'jin-photo')
}

db = SQLAlchemy(app)

# 데이터베이스 모델 정의
class SavedText(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_default = db.Column(db.Boolean, default=False)

class SavedTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_default = db.Column(db.Boolean, default=False)

class InstagramAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create uploads folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 데이터베이스 초기화
with app.app_context():
    db.create_all()


def instagram_upload_image(image_path, caption, access_token, ig_user_id):
    image_url = request.host_url.rstrip('/') + '/' + image_path

    media_url = f"https://graph.facebook.com/v17.0/{ig_user_id}/media"
    media_params = {
        'image_url': image_url,
        'caption': caption,
        'access_token': access_token
    }
    media_response = requests.post(media_url, data=media_params)
    media_result = media_response.json()

    if 'id' not in media_result:
        logging.error(f"Instagram media creation failed: {media_result}")
        return False, f"Media creation failed: {media_result}"

    creation_id = media_result['id']

    publish_url = f"https://graph.facebook.com/v17.0/{ig_user_id}/media_publish"
    publish_params = {
        'creation_id': creation_id,
        'access_token': access_token
    }
    publish_response = requests.post(publish_url, data=publish_params)
    publish_result = publish_response.json()

    if 'id' not in publish_result:
        logging.error(f"Instagram publish failed: {publish_result}")
        return False, f"Publishing failed: {publish_result}"

    logging.info(f"Instagram post published successfully: {publish_result['id']}")
    return True, publish_result['id']

# 폴더 생성 함수
def create_upload_folders():
    folders = [
        os.path.join(UPLOAD_FOLDER, 'cakes', 'original'),
        os.path.join(UPLOAD_FOLDER, 'cakes', 'thumbnail'),
        os.path.join(UPLOAD_FOLDER, 'cakes', 'instagram'),
        os.path.join(UPLOAD_FOLDER, 'designs', 'backgrounds'),
        os.path.join(UPLOAD_FOLDER, 'designs', 'overlays'),
        os.path.join(UPLOAD_FOLDER, 'designs', 'templates')
    ]
    for folder in folders:
        os.makedirs(folder, exist_ok=True)

# 앱 시작 시 폴더 생성
create_upload_folders()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_image(file, folder_type='original'):
    """이미지 처리 및 저장"""
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_name = f"{timestamp}_{filename}"
    
    # 이미지 저장 경로
    if folder_type == 'original':
        save_path = os.path.join(UPLOAD_FOLDER, 'cakes', 'original', base_name)
    elif folder_type == 'thumbnail':
        save_path = os.path.join(UPLOAD_FOLDER, 'cakes', 'thumbnail', base_name)
    else:  # instagram
        save_path = os.path.join(UPLOAD_FOLDER, 'cakes', 'instagram', base_name)
    
    # 이미지 처리
    img = Image.open(file)
    
    if folder_type == 'thumbnail':
        img.thumbnail(THUMBNAIL_SIZE)
    elif folder_type == 'instagram':
        # 인스타그램 비율에 맞게 리사이즈 (1:1 또는 4:5)
        width, height = img.size
        if width > height:
            new_width = min(width, MAX_IMAGE_SIZE[0])
            new_height = int(new_width * height / width)
        else:
            new_height = min(height, MAX_IMAGE_SIZE[1])
            new_width = int(new_height * width / height)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # 이미지 저장
    img.save(save_path, quality=95, optimize=True)
    return os.path.join('uploads', 'cakes', folder_type, base_name)

def get_random_image(folder_path):
    """폴더에서 랜덤 이미지 선택"""
    if not os.path.exists(folder_path):
        return None
    images = [f for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
    if not images:
        return None
    return os.path.join(folder_path, random.choice(images))

@app.route('/')
def index():
    saved_texts = SavedText.query.order_by(SavedText.created_at.desc()).all()
    saved_tags = SavedTag.query.order_by(SavedTag.created_at.desc()).all()
    instagram_account = InstagramAccount.query.first()
    # 진 사진 랜덤 선택
    jin_photo_dir = os.path.join('static', 'uploads', 'designs', 'jin-photo')
    jin_photo = None
    if os.path.exists(jin_photo_dir):
        images = [f for f in os.listdir(jin_photo_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        if images:
            jin_photo = os.path.join(jin_photo_dir, random.choice(images))
    return render_template('index.html', 
        saved_texts=saved_texts,
        saved_tags=saved_tags,
        instagram_account=instagram_account,
        jin_photo=jin_photo
    )

@app.route('/save-text', methods=['POST'])
def save_text():
    text = request.form.get('text')
    is_default = request.form.get('is_default') == 'true'
    
    if is_default:
        # 기존 기본값 해제
        SavedText.query.filter_by(is_default=True).update({'is_default': False})
    
    new_text = SavedText(text=text, is_default=is_default)
    db.session.add(new_text)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/save-tag', methods=['POST'])
def save_tag():
    tag = request.form.get('tag')
    is_default = request.form.get('is_default') == 'true'
    
    if is_default:
        # 기존 기본값 해제
        SavedTag.query.filter_by(is_default=True).update({'is_default': False})
    
    new_tag = SavedTag(tag=tag, is_default=is_default)
    db.session.add(new_tag)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/delete-text/<int:id>', methods=['POST'])
def delete_text(id):
    text = SavedText.query.get_or_404(id)
    db.session.delete(text)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/delete-tag/<int:id>', methods=['POST'])
def delete_tag(id):
    tag = SavedTag.query.get_or_404(id)
    db.session.delete(tag)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/save-instagram', methods=['POST'])
def save_instagram():
    username = request.form.get('username')
    password = request.form.get('password')
    
    # 기존 계정이 있으면 업데이트, 없으면 새로 생성
    account = InstagramAccount.query.first()
    if account:
        account.username = username
        account.password = password
    else:
        account = InstagramAccount(username=username, password=password)
        db.session.add(account)
    
    db.session.commit()
    return jsonify({'success': True})

# @app.route('/upload', methods=['POST'])
# def upload():
#     if 'posts' not in request.files:
#         return jsonify({'success': False, 'error': '파일이 없습니다.'})
#
#     files = request.files.getlist('posts')
#     texts = request.form.getlist('text')
#     tags = request.form.getlist('tags')
#
#     uploaded_files = []
#     for file in files:
#         if file and allowed_file(file.filename):
#             # 원본, 썸네일, 인스타그램용 이미지 모두 생성
#             original_path = process_image(file, 'original')
#             thumbnail_path = process_image(file, 'thumbnail')
#             instagram_path = process_image(file, 'instagram')
#
#             uploaded_files.append({
#                 'original': original_path,
#                 'thumbnail': thumbnail_path,
#                 'instagram': instagram_path
#             })
#
#     # TODO: 인스타그램 업로드 로직 구현
#
#     return jsonify({
#         'success': True,
#         'files': uploaded_files
#     })

@app.route('/set-default-text/<int:id>', methods=['POST'])
def set_default_text(id):
    # 기존 기본값 해제
    SavedText.query.filter_by(is_default=True).update({'is_default': False})
    
    # 새로운 기본값 설정
    text = SavedText.query.get_or_404(id)
    text.is_default = True
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/set-default-tag/<int:id>', methods=['POST'])
def set_default_tag(id):
    # 기존 기본값 해제
    SavedTag.query.filter_by(is_default=True).update({'is_default': False})
    
    # 새로운 기본값 설정
    tag = SavedTag.query.get_or_404(id)
    tag.is_default = True
    db.session.commit()
    
    return jsonify({'success': True})

def instagram_upload_image(image_path, caption, access_token, ig_user_id):
    """
    Instagram Graph API를 사용해 이미지 업로드 및 게시물 생성하는 함수
    image_path: 업로드할 이미지 경로 (웹서버에서 접근 가능해야 함)
    caption: 게시물 캡션
    access_token: Instagram Graph API Access Token
    ig_user_id: Instagram 비즈니스 계정 또는 크리에이터 계정 사용자 ID
    """

    # 1) 이미지 URL을 만들어야 하는데, 인스타그램 API는 외부에서 접근 가능한 URL이 필요함
    # 따라서, 서버가 public URL을 제공해야 하며, 로컬일 경우는 어렵습니다.
    # 여기서는 임시로 localhost 기준 URL이라고 가정합니다.
    image_url = request.host_url.rstrip('/') + '/' + image_path  # ex) http://localhost:5000/uploads/cakes/instagram/20230519_xxx.jpg

    # 2) 미디어 객체 생성
    media_url = f"https://graph.facebook.com/v17.0/{ig_user_id}/media"
    media_params = {
        'image_url': image_url,
        'caption': caption,
        'access_token': access_token
    }

    media_response = requests.post(media_url, data=media_params)
    media_result = media_response.json()
    if 'id' not in media_result:
        return False, f"Media creation failed: {media_result}"

    creation_id = media_result['id']

    # 3) 게시물 게시
    publish_url = f"https://graph.facebook.com/v17.0/{ig_user_id}/media_publish"
    publish_params = {
        'creation_id': creation_id,
        'access_token': access_token
    }

    publish_response = requests.post(publish_url, data=publish_params)
    publish_result = publish_response.json()

    if 'id' not in publish_result:
        return False, f"Publishing failed: {publish_result}"

    return True, publish_result['id']


@app.route('/upload', methods=['POST'])
def upload():
    if 'posts' not in request.files:
        return jsonify({'success': False, 'error': '파일이 없습니다.'})

    files = request.files.getlist('posts')
    texts = request.form.getlist('text')
    tags = request.form.getlist('tags')

    instagram_account = InstagramAccount.query.first()
    if not instagram_account:
        return jsonify({'success': False, 'error': '인스타그램 계정이 등록되어 있지 않습니다.'})

    # TODO: 실제 Instagram User ID와 Access Token을 저장해서 가져와야 합니다.
    access_token = "IGAAJ9TRhsVZB1BZAE14WUY1ZAkFjYlp1c29LY2tZATXY3cmJSSkZAOSG8yTmN2OEVfTF94UXRfMGNxZAlpMM3NzbjZAGcE9Pd25XS3RjVmhXOTFkYWRqYUFxSXQ3cXJCTUlkV3FqeWV6bFNRN2xpWWV2Q2o4NWhrSmIzYXFYUllFeEw1MAZDZD"
    ig_user_id = "700720029128685"

    uploaded_files = []
    upload_results = []

    for i, file in enumerate(files):
        if file and allowed_file(file.filename):
            # 원본, 썸네일, 인스타그램용 이미지 모두 생성
            original_path = process_image(file, 'original')
            thumbnail_path = process_image(file, 'thumbnail')
            instagram_path = process_image(file, 'instagram')

            # 캡션은 텍스트와 태그 합쳐서 생성 (ex: 텍스트 + 태그)
            caption = ''
            if i < len(texts):
                caption += texts[i]
            if i < len(tags):
                caption += ' ' + tags[i]

            # caption에 대한 수정안(챗gpt)
            # caption = ''
            # if i < len(texts):
            #     caption += texts[i].strip()
            # if i < len(tags):
            #     tag_list = tags[i].split(',')  # 만약 태그가 콤마 구분이라면
            #     tags_str = ' '.join(f'#{t.strip()}' for t in tag_list if t.strip())
            #     caption += ' ' + tags_str
            # caption = caption.strip()



            # 인스타그램 업로드 시도
            success, result = instagram_upload_image(instagram_path, caption, access_token, ig_user_id)

            if not success:
                # 실패 시 에러 로그와 함께 클라이언트에 알림
                app.logger.error(f"Instagram upload failed: {result}")
                return jsonify({'success': False, 'error': result})


            upload_results.append({
                'file': instagram_path,
                'success': success,
                'result': result
            })

            uploaded_files.append({
                'original': original_path,
                'thumbnail': thumbnail_path,
                'instagram': instagram_path
            })

    return jsonify({
        'success': True,
        'files': uploaded_files,
        'instagram_uploads': upload_results
    })


if __name__ == '__main__':
    app.run(debug=True) 