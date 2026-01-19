from flask import Flask, request, render_template, jsonify
import qrcode
from io import BytesIO
import base64
import os
from datetime import datetime
from dotenv import load_dotenv
import secrets
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__)

# Supabase 클라이언트 초기화
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_ANON_KEY')

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL과 SUPABASE_ANON_KEY를 .env 파일에 설정해주세요.")

supabase: Client = create_client(supabase_url, supabase_key)

# Multi-language translations
TRANSLATIONS = {
    'ko': {
        'title': '제품 설치 등록',
        'product_info': '제품 정보',
        'model': '기종',
        'order_number': '수주번호',
        'serial_number': '호기',
        'current_installation_date': '현재 장착일',
        'not_registered': '미등록',
        'register_installation': '장착일 등록',
        'installation_date': '장착일',
        'carrier_info': '대차정보',
        'dealer_code': '딜러 코드',
        'register': '장착일 등록',
        'success': '장착일이 성공적으로 등록되었습니다.',
        'select_date': '장착일을 선택하세요',
        'enter_carrier': '대차정보를 입력하세요',
        'enter_dealer': '딜러 코드를 입력하세요',
        'date_format_error': '날짜를 YYYY-MM-DD 형식으로 입력해주세요.',
        'invalid_date': '올바른 날짜를 입력해주세요.',
        'error_occurred': '오류가 발생했습니다.',
        'dealer_required': '딜러 코드를 입력해주세요.',
    },
    'en': {
        'title': 'Product Installation Registration',
        'product_info': 'Product Information',
        'model': 'Model',
        'order_number': 'Order Number',
        'serial_number': 'Serial Number',
        'current_installation_date': 'Current Installation Date',
        'not_registered': 'Not Registered',
        'register_installation': 'Register Installation Date',
        'installation_date': 'Installation Date',
        'carrier_info': 'Carrier Info',
        'dealer_code': 'Dealer Code',
        'register': 'Register Installation',
        'success': 'Installation date has been successfully registered.',
        'select_date': 'Select installation date',
        'enter_carrier': 'Enter carrier/vehicle information',
        'enter_dealer': 'Enter dealer code',
        'date_format_error': 'Please enter date in YYYY-MM-DD format.',
        'invalid_date': 'Please enter a valid date.',
        'error_occurred': 'An error occurred.',
        'dealer_required': 'Please enter dealer code.',
    },
    'ja': {
        'title': '製品設置登録',
        'product_info': '製品情報',
        'model': '機種',
        'order_number': '受注番号',
        'serial_number': '号機',
        'current_installation_date': '現在の設置日',
        'not_registered': '未登録',
        'register_installation': '設置日登録',
        'installation_date': '設置日',
        'carrier_info': '車体情報',
        'dealer_code': 'ディーラーコード',
        'register': '設置日を登録',
        'success': '設置日が正常に登録されました。',
        'select_date': '設置日を選択してください',
        'enter_carrier': '車体情報を入力してください',
        'enter_dealer': 'ディーラーコードを入力してください',
        'date_format_error': '日付はYYYY-MM-DD形式で入力してください。',
        'invalid_date': '正しい日付を入力してください。',
        'error_occurred': 'エラーが発生しました。',
        'dealer_required': 'ディーラーコードを入力してください。',
    },
    'zh': {
        'title': '产品安装登记',
        'product_info': '产品信息',
        'model': '型号',
        'order_number': '订单号',
        'serial_number': '序列号',
        'current_installation_date': '当前安装日期',
        'not_registered': '未登记',
        'register_installation': '登记安装日期',
        'installation_date': '安装日期',
        'carrier_info': '车辆信息',
        'dealer_code': '经销商代码',
        'register': '登记安装',
        'success': '安装日期已成功登记。',
        'select_date': '选择安装日期',
        'enter_carrier': '输入车辆信息',
        'enter_dealer': '输入经销商代码',
        'date_format_error': '请按YYYY-MM-DD格式输入日期。',
        'invalid_date': '请输入有效日期。',
        'error_occurred': '发生错误。',
        'dealer_required': '请输入经销商代码。',
    },
    'id': {
        'title': 'Pendaftaran Instalasi Produk',
        'product_info': 'Informasi Produk',
        'model': 'Model',
        'order_number': 'Nomor Pesanan',
        'serial_number': 'Nomor Seri',
        'current_installation_date': 'Tanggal Instalasi Saat Ini',
        'not_registered': 'Belum Terdaftar',
        'register_installation': 'Daftar Tanggal Instalasi',
        'installation_date': 'Tanggal Instalasi',
        'carrier_info': 'Info Kendaraan',
        'dealer_code': 'Kode Dealer',
        'register': 'Daftar Instalasi',
        'success': 'Tanggal instalasi berhasil didaftarkan.',
        'select_date': 'Pilih tanggal instalasi',
        'enter_carrier': 'Masukkan informasi kendaraan',
        'enter_dealer': 'Masukkan kode dealer',
        'date_format_error': 'Masukkan tanggal dalam format YYYY-MM-DD.',
        'invalid_date': 'Masukkan tanggal yang valid.',
        'error_occurred': 'Terjadi kesalahan.',
        'dealer_required': 'Masukkan kode dealer.',
    },
    'es': {
        'title': 'Registro de Instalacion de Producto',
        'product_info': 'Informacion del Producto',
        'model': 'Modelo',
        'order_number': 'Numero de Pedido',
        'serial_number': 'Numero de Serie',
        'current_installation_date': 'Fecha de Instalacion Actual',
        'not_registered': 'No Registrado',
        'register_installation': 'Registrar Fecha de Instalacion',
        'installation_date': 'Fecha de Instalacion',
        'carrier_info': 'Informacion del Vehiculo',
        'dealer_code': 'Codigo de Distribuidor',
        'register': 'Registrar Instalacion',
        'success': 'La fecha de instalacion se ha registrado correctamente.',
        'select_date': 'Seleccione la fecha de instalacion',
        'enter_carrier': 'Ingrese informacion del vehiculo',
        'enter_dealer': 'Ingrese codigo de distribuidor',
        'date_format_error': 'Ingrese la fecha en formato YYYY-MM-DD.',
        'invalid_date': 'Ingrese una fecha valida.',
        'error_occurred': 'Se produjo un error.',
        'dealer_required': 'Ingrese el codigo de distribuidor.',
    },
}

# Country to language mapping
COUNTRY_LANG_MAP = {
    # Korean
    '한국': 'ko', 'Korea': 'ko', 'South Korea': 'ko', 'KR': 'ko',
    # English (default for most)
    '미국': 'en', 'USA': 'en', 'United States': 'en', 'US': 'en',
    '영국': 'en', 'UK': 'en', 'United Kingdom': 'en', 'GB': 'en',
    '호주': 'en', 'Australia': 'en', 'AU': 'en',
    '캐나다': 'en', 'Canada': 'en', 'CA': 'en',
    '인도': 'en', 'India': 'en', 'IN': 'en',
    # Japanese
    '일본': 'ja', 'Japan': 'ja', 'JP': 'ja',
    # Chinese
    '중국': 'zh', 'China': 'zh', 'CN': 'zh',
    '대만': 'zh', 'Taiwan': 'zh', 'TW': 'zh',
    '홍콩': 'zh', 'Hong Kong': 'zh', 'HK': 'zh',
    # Indonesian
    '인도네시아': 'id', 'Indonesia': 'id', 'ID': 'id',
    # Spanish
    '스페인': 'es', 'Spain': 'es', 'ES': 'es',
    '멕시코': 'es', 'Mexico': 'es', 'MX': 'es',
    '아르헨티나': 'es', 'Argentina': 'es', 'AR': 'es',
    '칠레': 'es', 'Chile': 'es', 'CL': 'es',
    '콜롬비아': 'es', 'Colombia': 'es', 'CO': 'es',
    '페루': 'es', 'Peru': 'es', 'PE': 'es',
}


def get_language(equipment, req):
    """Determine language based on priority:
    1. export_country from equipment record
    2. Browser Accept-Language header
    3. Default: English
    """
    # Priority 1: Export country based
    export_country = equipment.get('export_country', '')
    if export_country and export_country in COUNTRY_LANG_MAP:
        return COUNTRY_LANG_MAP[export_country]

    # Priority 2: Browser language setting
    supported_langs = ['en', 'ko', 'ja', 'zh', 'id', 'es']
    browser_lang = req.accept_languages.best_match(supported_langs)
    if browser_lang:
        return browser_lang

    # Default: English
    return 'en'


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_qr', methods=['POST'])
def generate_qr():
    try:
        model = request.form.get('model')
        order_number = request.form.get('order_number')
        unit_number = request.form.get('unit_number')
        export_country = request.form.get('export_country')
        shipment_date = request.form.get('shipment_date')

        if not model or not unit_number:
            return jsonify({'error': '모델과 호기 번호를 모두 입력해주세요.'}), 400

        if not order_number:
            return jsonify({'error': '수주번호를 입력해주세요.'}), 400

        if not export_country or not shipment_date:
            return jsonify({'error': '수출 국가와 출하일을 모두 입력해주세요.'}), 400

        # 고유한 토큰 생성 (32바이트)
        access_token = secrets.token_urlsafe(32)

        # QR 등록일은 오늘 날짜
        qr_registered_date = datetime.now().strftime('%Y-%m-%d')

        try:
            # 기존 장비가 있는지 확인
            existing = supabase.table('equipment').select('id').eq('model', model).eq('unit_number', unit_number).execute()

            if existing.data:
                # 업데이트: 토큰, 출하일, 수출국가, QR등록일, 수주번호 갱신
                supabase.table('equipment').update({
                    'access_token': access_token,
                    'order_number': order_number,
                    'export_country': export_country,
                    'shipment_date': shipment_date,
                    'qr_registered_date': qr_registered_date,
                    'updated_at': datetime.utcnow().isoformat()
                }).eq('model', model).eq('unit_number', unit_number).execute()
            else:
                # 신규 삽입
                supabase.table('equipment').insert({
                    'model': model,
                    'order_number': order_number,
                    'unit_number': unit_number,
                    'access_token': access_token,
                    'export_country': export_country,
                    'shipment_date': shipment_date,
                    'qr_registered_date': qr_registered_date
                }).execute()

        except Exception as db_error:
            print(f"Database operation error: {db_error}")
            return jsonify({'error': f'데이터베이스 오류: {str(db_error)}'}), 500

        # QR 코드에 포함될 URL 생성 (토큰 기반)
        server_url = os.getenv('SERVER_URL', 'http://localhost:5000')
        qr_data = f"{server_url}/scan/{access_token}"

        # QR 코드 생성
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # 이미지를 base64로 인코딩
        buffered = BytesIO()
        img.save(buffered)
        img_str = base64.b64encode(buffered.getvalue()).decode()

        return jsonify({'qr_code': img_str})

    except Exception as e:
        print(f"General error in generate_qr: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/scan/<token>')
def scan(token):
    try:
        # 토큰으로 장비 정보 조회 (carrier_info, dealer_code 포함)
        result = supabase.table('equipment').select(
            'id, model, order_number, unit_number, installation_date, '
            'export_country, qr_registered_date, shipment_date, carrier_info, dealer_code'
        ).eq('access_token', token).execute()

        if not result.data:
            return "Invalid QR code.", 404

        equipment = result.data[0]

        # 언어 결정 (export_country 기반 또는 브라우저 설정)
        lang = get_language(equipment, request)
        t = TRANSLATIONS.get(lang, TRANSLATIONS['en'])

        # 오늘 날짜를 템플릿에 전달
        today = datetime.now().strftime('%Y-%m-%d')

        return render_template('scan.html', equipment=equipment, today=today, lang=lang, t=t)

    except Exception as e:
        print(f"Error in scan: {e}")
        return str(e), 500

@app.route('/update_installation_date', methods=['POST'])
def update_installation_date():
    try:
        equipment_id = request.form.get('equipment_id')
        installation_date = request.form.get('installation_date')
        carrier_info = request.form.get('carrier_info', '')
        dealer_code = request.form.get('dealer_code', '')

        if not equipment_id or not installation_date:
            return jsonify({'error': '필수 정보가 누락되었습니다.'}), 400

        if not dealer_code:
            return jsonify({'error': '딜러 코드를 입력해주세요.'}), 400

        # 장착일 및 추가 정보 업데이트
        supabase.table('equipment').update({
            'installation_date': installation_date,
            'carrier_info': carrier_info,
            'dealer_code': dealer_code,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('id', equipment_id).execute()

        return jsonify({'message': '장착일이 성공적으로 등록되었습니다.'})

    except Exception as e:
        print(f"Error in update_installation_date: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/dashboard')
def dashboard():
    try:
        # 전체 장비 데이터 조회
        all_equipment = supabase.table('equipment').select('*').order('created_at', desc=True).execute()

        # 판매 대기중 (installation_date가 null)
        pending = [eq for eq in all_equipment.data if not eq.get('installation_date')]

        # 판매 완료 (installation_date가 있는 것)
        completed = [eq for eq in all_equipment.data if eq.get('installation_date')]

        # 각 장비에 QR 코드 생성 (판매 대기중)
        server_url = os.getenv('SERVER_URL', 'http://localhost:5000')
        for eq in pending:
            qr_data = f"{server_url}/scan/{eq['access_token']}"
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffered = BytesIO()
            img.save(buffered)
            eq['qr_code'] = base64.b64encode(buffered.getvalue()).decode()

        # 기종별 통계
        model_stats = {}
        for eq in all_equipment.data:
            model = eq['model']
            if model not in model_stats:
                model_stats[model] = {'total': 0, 'completed': 0, 'pending': 0}
            model_stats[model]['total'] += 1
            if eq.get('installation_date'):
                model_stats[model]['completed'] += 1
            else:
                model_stats[model]['pending'] += 1

        # 월별 통계 (최근 6개월)
        monthly_stats = {}
        for eq in completed:
            if eq.get('installation_date'):
                # installation_date가 문자열 형태로 저장되어 있을 수 있음
                date_str = eq['installation_date']
                if isinstance(date_str, str):
                    date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    date_obj = date_str
                month_key = date_obj.strftime('%Y-%m')
                monthly_stats[month_key] = monthly_stats.get(month_key, 0) + 1

        # 월별 통계를 정렬
        sorted_months = sorted(monthly_stats.items())[-6:]  # 최근 6개월

        # 리드타임 분석 (장착일 - 출하일 차이)
        lead_times = []
        lead_time_ranges = {'0-7일': 0, '8-14일': 0, '15-30일': 0, '31-60일': 0, '60일+': 0}

        for eq in completed:
            if eq.get('installation_date') and eq.get('shipment_date'):
                # 출하일 사용
                shipment_str = eq.get('shipment_date')
                install_str = eq['installation_date']

                if shipment_str:
                    # shipment_date를 날짜로 변환 (시간 무시)
                    if isinstance(shipment_str, str):
                        # DATE 형식 (shipment_date)
                        shipment_date = datetime.strptime(shipment_str[:10], '%Y-%m-%d').date()
                    else:
                        shipment_date = shipment_str.date() if hasattr(shipment_str, 'date') else shipment_str

                    # installation_date를 날짜로 변환
                    if isinstance(install_str, str):
                        # DATE 타입은 'YYYY-MM-DD' 형식의 문자열
                        install_date = datetime.strptime(install_str[:10], '%Y-%m-%d').date()
                    else:
                        install_date = install_str.date() if hasattr(install_str, 'date') else install_str

                    # 날짜 차이 계산 (시간 무시): 장착일 - 출하일
                    lead_time = (install_date - shipment_date).days
                    lead_times.append(lead_time)

                    # 범위별 분류
                    if lead_time <= 7:
                        lead_time_ranges['0-7일'] += 1
                    elif lead_time <= 14:
                        lead_time_ranges['8-14일'] += 1
                    elif lead_time <= 30:
                        lead_time_ranges['15-30일'] += 1
                    elif lead_time <= 60:
                        lead_time_ranges['31-60일'] += 1
                    else:
                        lead_time_ranges['60일+'] += 1

        avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else 0

        dashboard_data = {
            'pending': pending,
            'completed': completed,
            'total_count': len(all_equipment.data),
            'pending_count': len(pending),
            'completed_count': len(completed),
            'model_stats': model_stats,
            'monthly_stats': dict(sorted_months),
            'avg_lead_time': round(avg_lead_time, 1),
            'lead_time_ranges': lead_time_ranges
        }

        return render_template('dashboard.html', data=dashboard_data)

    except Exception as e:
        print(f"Error in dashboard: {e}")
        return str(e), 500

if __name__ == '__main__':
    # PythonAnywhere에서는 이 부분이 실행되지 않습니다
    # 로컬 개발 환경에서만 사용됩니다
    if os.getenv('PYTHONANYWHERE_DOMAIN') is None:
        app.run(host='0.0.0.0', port=5000, debug=True)
    else:
        app.run()
