from flask import Flask, request, render_template, jsonify
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import secrets
import requests
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__)

# Supabase 클라이언트 초기화
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_ANON_KEY')

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL과 SUPABASE_ANON_KEY를 .env 파일에 설정해주세요.")

supabase: Client = create_client(supabase_url, supabase_key)


# ── QR 스캔 API (ERP에서 생성한 QR을 웹에서 스캔) ─────────────────────
@app.route('/api/scan_qr', methods=['POST'])
def api_scan_qr():
    """카메라로 스캔한 QR 데이터를 파싱하여 저장

    QR 형식: 제품코드?제품명?제품그룹명?호기?거래처 (거래처는 선택)
    """
    try:
        data = request.get_json()
        qr_data = data.get('qr_data', '') if data else ''

        if not qr_data:
            return jsonify({'error': 'QR 데이터가 없습니다.'}), 400

        # 파싱: 제품코드?제품명?제품그룹명?호기?거래처(선택)
        parts = qr_data.split('?')
        if len(parts) < 4 or len(parts) > 5:
            return jsonify({'error': '잘못된 QR 형식입니다. (4~5개 항목 필요)'}), 400

        product_code = parts[0]
        product_name = parts[1]
        product_group = parts[2]
        unit_number = parts[3]
        customer = parts[4] if len(parts) == 5 else ''

        # 필수값 검증
        if not product_code or not unit_number:
            return jsonify({'error': '제품코드와 호기는 필수입니다.'}), 400

        # 중복 확인 (product_code 기준)
        existing = supabase.table('equipment').select('id, access_token, installation_date').eq(
            'product_code', product_code
        ).execute()

        if existing.data:
            # 이미 존재 → 기존 데이터 반환
            equip = existing.data[0]
            return jsonify({
                'status': 'exists',
                'product_group': product_group,
                'unit_number': unit_number,
                'access_token': equip['access_token'],
                'already_installed': equip.get('installation_date') is not None
            })

        # 신규 → INSERT (created_at은 Supabase에서 자동 생성)
        access_token = secrets.token_urlsafe(32)

        supabase.table('equipment').insert({
            'product_code': product_code,
            'product_name': product_name,
            'model': product_group,  # 기존 model 컬럼에 제품그룹명 저장
            'unit_number': unit_number,
            'customer': customer,
            'access_token': access_token
        }).execute()

        return jsonify({
            'status': 'created',
            'product_group': product_group,
            'unit_number': unit_number,
            'access_token': access_token
        })

    except Exception as e:
        print(f"QR scan error: {e}")
        return jsonify({'error': f'처리 중 오류가 발생했습니다: {str(e)}'}), 500


@app.route('/api/equipment/<product_code>', methods=['GET'])
def api_get_equipment(product_code):
    """ERP에서 장비 정보 조회용 API (단일 제품)

    사용법: GET /api/equipment/SCB330L001
    """
    try:
        result = supabase.table('equipment').select('*').eq(
            'product_code', product_code
        ).execute()

        if not result.data:
            return jsonify({'error': '장비를 찾을 수 없습니다.'}), 404

        return jsonify(result.data[0])

    except Exception as e:
        print(f"Equipment lookup error: {e}")
        return jsonify({'error': f'조회 중 오류가 발생했습니다: {str(e)}'}), 500


@app.route('/api/equipment', methods=['GET'])
def api_list_equipment():
    """ERP에서 장비 목록 조회용 API

    쿼리 파라미터:
    - status: 'pending' (미등록) / 'completed' (판매완료) / 'all' (전체, 기본값)
    - from_date: 등록일 시작 (YYYY-MM-DD)
    - to_date: 등록일 종료 (YYYY-MM-DD)
    - model: 기종(제품그룹명) 필터
    - limit: 조회 개수 (기본값 100, 최대 1000)
    - offset: 시작 위치 (페이징용)

    사용 예시:
    - GET /api/equipment?status=completed
    - GET /api/equipment?from_date=2025-01-01&to_date=2025-01-31
    - GET /api/equipment?model=브레이커&status=pending
    """
    try:
        status = request.args.get('status', 'all')
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
        model = request.args.get('model')
        limit = min(int(request.args.get('limit', 100)), 1000)
        offset = int(request.args.get('offset', 0))

        # 기본 쿼리
        query = supabase.table('equipment').select('*')

        # 상태 필터
        if status == 'pending':
            query = query.is_('installation_date', 'null')
        elif status == 'completed':
            query = query.not_.is_('installation_date', 'null')

        # 날짜 필터 (created_at 기준)
        if from_date:
            query = query.gte('created_at', from_date)
        if to_date:
            query = query.lte('created_at', to_date + 'T23:59:59')

        # 기종 필터
        if model:
            query = query.eq('model', model)

        # 페이징 및 정렬
        query = query.order('created_at', desc=True).range(offset, offset + limit - 1)

        result = query.execute()

        return jsonify({
            'count': len(result.data),
            'offset': offset,
            'limit': limit,
            'data': result.data
        })

    except Exception as e:
        print(f"Equipment list error: {e}")
        return jsonify({'error': f'조회 중 오류가 발생했습니다: {str(e)}'}), 500


@app.route('/api/equipment/bulk', methods=['POST'])
def api_bulk_equipment():
    """ERP에서 여러 제품 한번에 조회

    요청 본문:
    {
        "product_codes": ["SCB330L001", "SCB330L002", "SCB450001"]
    }

    응답:
    {
        "found": [...],      // 찾은 장비 목록
        "not_found": [...]   // 찾지 못한 제품코드 목록
    }
    """
    try:
        data = request.get_json()
        product_codes = data.get('product_codes', [])

        if not product_codes:
            return jsonify({'error': '제품코드 목록이 필요합니다.'}), 400

        if len(product_codes) > 100:
            return jsonify({'error': '한 번에 최대 100개까지 조회 가능합니다.'}), 400

        result = supabase.table('equipment').select('*').in_(
            'product_code', product_codes
        ).execute()

        found_codes = {eq['product_code'] for eq in result.data}
        not_found = [code for code in product_codes if code not in found_codes]

        return jsonify({
            'found': result.data,
            'not_found': not_found
        })

    except Exception as e:
        print(f"Bulk equipment lookup error: {e}")
        return jsonify({'error': f'조회 중 오류가 발생했습니다: {str(e)}'}), 500


@app.route('/api/stats', methods=['GET'])
def api_stats():
    """ERP에서 통계 조회용 API

    응답:
    {
        "total": 전체 장비 수,
        "pending": 딜러 재고 수,
        "completed": 판매 완료 수,
        "by_model": { "브레이커": {"total": 10, "pending": 3, "completed": 7}, ... }
    }
    """
    try:
        result = supabase.table('equipment').select('model, installation_date').execute()

        total = len(result.data)
        pending = sum(1 for eq in result.data if not eq.get('installation_date'))
        completed = total - pending

        # 기종별 통계
        by_model = {}
        for eq in result.data:
            model = eq.get('model', '미분류')
            if model not in by_model:
                by_model[model] = {'total': 0, 'pending': 0, 'completed': 0}
            by_model[model]['total'] += 1
            if eq.get('installation_date'):
                by_model[model]['completed'] += 1
            else:
                by_model[model]['pending'] += 1

        return jsonify({
            'total': total,
            'pending': pending,
            'completed': completed,
            'by_model': by_model
        })

    except Exception as e:
        print(f"Stats error: {e}")
        return jsonify({'error': f'통계 조회 중 오류가 발생했습니다: {str(e)}'}), 500
# ─────────────────────────────────────────────────────────────────────


def get_location_from_ip(ip_address):
    """IP 주소로 대략적인 위치 정보 조회 (GPS fallback용)"""
    try:
        # localhost나 private IP는 건너뛰기
        if ip_address in ['127.0.0.1', 'localhost'] or ip_address.startswith('192.168.') or ip_address.startswith('10.'):
            return None

        # ip-api.com 무료 서비스 (일일 45회/분 제한, 상용은 유료)
        response = requests.get(f'http://ip-api.com/json/{ip_address}', timeout=5)
        data = response.json()

        if data.get('status') == 'success':
            return {
                'latitude': data.get('lat'),
                'longitude': data.get('lon'),
                'city': data.get('city'),
                'country': data.get('country'),
                'source': 'ip'
            }
    except Exception as e:
        print(f"IP Geolocation error: {e}")
    return None


# 딜러 코드 → 딜러명 매핑
DEALER_MAP = {
    '9000400467': 'SMITHBRIDGE GUAM INC.',
    '9000400041': 'Antony Pagidas',
    '9000400365': 'HIGH POWER EQUIPMENT AFRICA',
    '9000411503': "van't Hof Techniek",
    '9000411406': 'Reesink Construction Equipment NL B',
    '9000400299': 'PELLEN MACHINES BV',
    '9000400148': 'Volvo Maskin AS',
    '9000400345': 'Tecklenborg GmbH',
    '9000400771': 'SCHMID BAUMASCHINEN GMBH',
    '9000400370': 'Mann & Magar GmbH',
    '9000400755': 'F.Schunke GmbH',
    '9000400653': 'BVG BAUMASCHINEN GMBH',
    '9000400500': 'Bau Suddeutsche Baum.Hanels GmbH',
    '9000411325': 'ATLAS THURINGEN SUHL Miet- und Serv',
    '9000400346': 'Atlas Thuringen GmbH',
    '9000400411': 'Atlas Rostock GmbH',
    '9000400317': 'Atlas Leipzig Gmbh',
    '9000411202': 'AP Construction and',
    '9000411478': 'URALPROMSERVIS',
    '9000400165': 'KAMAL KAHI &SONS',
    '9000400887': '3F Impex srl',
    '9000400143': 'UAB TECHNIKOS JEGA',
    '9000411607': 'Hugo Schadler AG',
    '9000411496': 'SYN TAI HUNG MARKETING SDN BHD',
    '9000411627': 'MALTU PTE LTD',
    '9000400728': 'Equipos Mejores S.A. de C.V.',
    '9000411360': 'ASIA MAQUINARIA DE MEXICO S.A. DE C.V.',
    '9000411611': 'DIMAINTSA S.A. de C.V.',
    '9000400678': 'DIMAPESA SA dv cv',
    '9000400450': 'HYDRAU MAC S. A. R. L.',
    '9000400221': 'MECOM',
    '9000400123': 'SR Service',
    '9000400930': 'Soosan USA, Inc.',
    '9000400175': 'Sayed Kadhem Al Durazi & Sons Co.',
    '9000411309': 'Y.K ALMOAYYED & SONS',
    '9000411323': 'TUNG LINH HYDRAULICS BREAKER JSC',
    '9000411636': 'TRAN HONG PHAT',
    '9000400651': 'Hiep Hoa Special Purpose Vehicle JSC',
    '9000411364': 'Reesink Construction Equipment Belg',
    '9000411670': 'HARZAK SRL',
    '9000411721': 'Lager d.o.o.',
    '9000400152': 'A.ABUNAYYAN TRADING CORP.',
    '9000400921': 'RECON OPREMA DOO',
    '9000400075': 'HAND BAUMASCHINEN AG',
    '9000411655': 'Lera Maquinaria S.L',
    '9000400080': 'Intertrac SA',
    '9000411282': 'Exclusivas Generales Adal S.L',
    '9000411495': 'ALIGRAS EQUIPOS, S.L.U.',
    '9000400405': 'Quarry Mining LLC',
    '9000400496': 'STEVIN ROCK L.L.C.',
    '9000411369': 'ACTION EXPRESS ELECTRONICS L.L.C',
    '9000411605': 'SELMAN',
    '9000411680': 'KS MACHINERY',
    '9000411591': 'CORRECT METHOD GOODS WHOLESALERS L.L.C',
    '9000411368': 'Brave Dwellfront General Trading LLC',
    '9000411514': 'SHOVEL',
    '9000411366': 'ALDA Construction',
    '9000411374': 'H&H MATINI GENERAL TRADING LLC',
    '9000411407': 'RADIX',
    '9000411499': 'MEGA ZONE',
    '9000411783': 'United Motors & Heavy Equipment Co.L.L.C.',
    '9000411376': 'GOMAS GENERAL TRADING LLC',
    '9000411599': 'SMARTEX',
    '9000411668': 'METATECH',
    '9000400601': 'REPAS SOCIEDAD ANONIMA',
    '9000400650': 'CAMBIUM INTERNATIONAL, INC',
    '9000411329': 'EURL SOSKA',
    '9000411642': 'Hammer Service O',
    '9000400892': 'GEDEQUIP',
    '9000400495': 'MWE',
    '9000411570': 'SUNBELT',
    '9000400154': 'AL FAIRUZ TRAD. & CONT. CO. LLC.',
    '9000400320': 'Bulldozer Handels Gmbh',
    '9000411485': 'CNC INTERNATIONAL LIMITED',
    '9000400931': 'Bethlehem Hydraulic',
    '9000411505': 'AL-MADINA Contracting Company',
    '9000411760': 'Frenda Machine Srl',
    '9000400373': 'Franceschino Gianni Service',
    '9000400661': 'Om Hydraulics Equipments',
    '9000400693': 'MANITOU EQUIPMENT INDIA PVT LTD',
    '9000411461': 'M/S. UTKAL AGRO INTERNATIONAAL',
    '9000411672': 'MANDA PROJECTS PRIVATE LIMITED',
    '9000411701': 'JAY CONSTRUCTION EQUIPMENTS',
    '9000400342': 'VOLVO CE INDIA PRIVATE LIMITED',
    '9000400233': 'PT.AIRINDO SAKTI',
    '9000411455': 'Yanmar Construction Equipment CO.,LTD',
    '9000400807': 'XINSOOSAN HEAVY INDUSTRY(QINGDAO) CO.,LT',
    '9000400608': 'AH Servis',
    '9000400158': 'GOLDEN HYDRAULIC TECHNICAL CENTER',
    '9000400538': 'Farm Engineering Industries Limitd',
    '9000411410': 'Riham General Trading Co.',
    '9000400576': 'Maxtech d.o.o',
    '9000411667': 'Lager Basic d.o.o.',
    '9000400104': 'Michalakis Pateras Trading Ltd',
    '9000411425': 'GF TRUCKS & EQUIPMENT LTD',
    '9000400282': 'WILLIAM WONG GROUP CO., LTD.',
    '9000400746': 'P.V.MINING AND EXPLORATION CO.,LTD',
    '9000400258': 'World Tractor (1996) Co., Ltd.',
    '9000411371': 'AL MAKIYAL',
    '9000411513': 'EMSAMAK',
    '9000400128': 'SO.TU.DIS.SA',
    '9000400029': 'SAMGWANG CORPORATION PANAMA',
    '9000411709': 'Carvalho, Coimbra & Esteves, Lda.',
    '9000401332': 'POWERS MASZYNY Sp. z o.o.',
    '9000400894': 'Tahiti Automobiles SA',
    '9000411763': 'RTX',
    '9000411545': 'Arma Distribution',
    '9000411311': 'GRACE ROAD FOOD COMPANY LIMITED',
    '9000411692': 'Normet MRB Oy',
    '9000400622': 'MRK-Rent Oy',
    '9000400524': 'Marakon Oy',
    '9000400201': 'CIVIC MERCHANDISING, INC',
    '9000411619': 'Kotroalkatresz Kft.',
    '9000400278': 'AUSTAS HAMMERS & ACCESSORIES',
    '9000400238': 'SHING LEE MACHINERY LIMITED',
    '9000400680': 'T-Smart Logistics Ltd',
}


# Multi-language translations (26 languages)
TRANSLATIONS = {
    'ko': {
        'title': '제품 설치 등록',
        'product_info': '제품 정보',
        'model': '기종',
        'serial_number': '호기',
        'current_installation_date': '현재 장착일',
        'not_registered': '미등록',
        'register_installation': '장착일 등록',
        'installation_date': '고객인도일',
        'carrier_info': '대차정보',
        'dealer_code': '딜러명',
        'register': '장착일 등록',
        'success': '장착일이 성공적으로 등록되었습니다.',
        'select_date': '장착일을 선택하세요',
        'enter_carrier': '대차정보를 입력하세요',
        'enter_dealer': '딜러명을 입력하세요',
        'date_format_error': '날짜를 YYYY-MM-DD 형식으로 입력해주세요.',
        'invalid_date': '올바른 날짜를 입력해주세요.',
        'error_occurred': '오류가 발생했습니다.',
        'dealer_required': '딜러명을 입력해주세요.',
        'carrier_required': '대차정보를 입력해주세요.',
        'verification_title': '정품 인증 확인',
        'authentic_product': '정품 등록 완료',
        'verification_confirmed': '이 제품은 정품으로 등록되었습니다.',
        'registration_info': '등록 정보',
        'registration_date': '등록 일시',
        'registration_location': '등록 위치',
        'view_on_map': '지도에서 보기',
        'already_registered': '이미 등록된 장비입니다.',
        'location_consent': '위치 정보 수집에 동의하시겠습니까?',
        'location_consent_note': '(거부해도 등록은 가능합니다)',
        'manufacturer': '제조사',
        'manufacturer_name': '수산세보틱스',
        'country_of_origin': '제조국',
        'country_name': '대한민국 (Made in Korea)',
    },
    'en': {
        'title': 'Product Installation Registration',
        'product_info': 'Product Information',
        'model': 'Model',
        'serial_number': 'Serial Number',
        'current_installation_date': 'Current Installation Date',
        'not_registered': 'Not Registered',
        'register_installation': 'Register Installation Date',
        'installation_date': 'Customer Delivery Date',
        'carrier_info': 'Carrier Info',
        'dealer_code': 'Dealer Name',
        'register': 'Register Installation',
        'success': 'Installation date has been successfully registered.',
        'select_date': 'Select installation date',
        'enter_carrier': 'Enter carrier/vehicle information',
        'enter_dealer': 'Enter dealer name',
        'date_format_error': 'Please enter date in YYYY-MM-DD format.',
        'invalid_date': 'Please enter a valid date.',
        'error_occurred': 'An error occurred.',
        'dealer_required': 'Please enter dealer name.',
        'carrier_required': 'Please enter carrier info.',
        'verification_title': 'Product Authenticity Verification',
        'authentic_product': 'Authentic Product Verified',
        'verification_confirmed': 'This product has been verified as authentic.',
        'registration_info': 'Registration Information',
        'registration_date': 'Registration Date/Time',
        'registration_location': 'Registration Location',
        'view_on_map': 'View on Map',
        'already_registered': 'Equipment already registered.',
        'location_consent': 'Do you consent to location data collection?',
        'location_consent_note': '(You can still register without providing location)',
        'manufacturer': 'Manufacturer',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Country of Origin',
        'country_name': 'Republic of Korea (Made in Korea)',
    },
    'ja': {
        'title': '製品設置登録',
        'product_info': '製品情報',
        'model': '機種',
        'serial_number': '号機',
        'current_installation_date': '現在の設置日',
        'not_registered': '未登録',
        'register_installation': '設置日登録',
        'installation_date': '納品日',
        'carrier_info': '車体情報',
        'dealer_code': 'ディーラー名',
        'register': '設置日を登録',
        'success': '設置日が正常に登録されました。',
        'select_date': '設置日を選択してください',
        'enter_carrier': '車体情報を入力してください',
        'enter_dealer': 'ディーラー名を入力してください',
        'date_format_error': '日付はYYYY-MM-DD形式で入力してください。',
        'invalid_date': '正しい日付を入力してください。',
        'error_occurred': 'エラーが発生しました。',
        'dealer_required': 'ディーラー名を入力してください。',
        'carrier_required': '車体情報を入力してください。',
        'verification_title': '正規品認証確認',
        'authentic_product': '正規品認証完了',
        'verification_confirmed': 'この製品は正規品として登録されています。',
        'registration_info': '登録情報',
        'registration_date': '登録日時',
        'registration_location': '登録位置',
        'view_on_map': '地図で見る',
        'already_registered': '既に登録済みの機器です。',
        'location_consent': '位置情報の収集に同意しますか？',
        'location_consent_note': '（拒否しても登録は可能です）',
        'manufacturer': 'メーカー',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': '製造国',
        'country_name': '大韓民国 (Made in Korea)',
    },
    'zh': {
        'title': '产品安装登记',
        'product_info': '产品信息',
        'model': '型号',
        'serial_number': '序列号',
        'current_installation_date': '当前安装日期',
        'not_registered': '未登记',
        'register_installation': '登记安装日期',
        'installation_date': '交货日期',
        'carrier_info': '车辆信息',
        'dealer_code': '经销商名称',
        'register': '登记安装',
        'success': '安装日期已成功登记。',
        'select_date': '选择安装日期',
        'enter_carrier': '输入车辆信息',
        'enter_dealer': '输入经销商名称',
        'date_format_error': '请按YYYY-MM-DD格式输入日期。',
        'invalid_date': '请输入有效日期。',
        'error_occurred': '发生错误。',
        'dealer_required': '请输入经销商名称。',
        'carrier_required': '请输入车辆信息。',
        'verification_title': '正品认证验证',
        'authentic_product': '正品认证完成',
        'verification_confirmed': '该产品已被验证为正品。',
        'registration_info': '登记信息',
        'registration_date': '登记日期时间',
        'registration_location': '登记位置',
        'view_on_map': '在地图上查看',
        'already_registered': '设备已登记。',
        'location_consent': '您同意收集位置信息吗？',
        'location_consent_note': '（拒绝也可以完成登记）',
        'manufacturer': '制造商',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': '原产国',
        'country_name': '大韩民国 (Made in Korea)',
    },
    'id': {
        'title': 'Pendaftaran Instalasi Produk',
        'product_info': 'Informasi Produk',
        'model': 'Model',
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
        'verification_title': 'Verifikasi Keaslian Produk',
        'authentic_product': 'Produk Asli Terverifikasi',
        'verification_confirmed': 'Produk ini telah diverifikasi sebagai produk asli.',
        'registration_info': 'Informasi Pendaftaran',
        'registration_date': 'Tanggal/Waktu Pendaftaran',
        'registration_location': 'Lokasi Pendaftaran',
        'view_on_map': 'Lihat di Peta',
        'already_registered': 'Peralatan sudah terdaftar.',
        'location_consent': 'Apakah Anda menyetujui pengumpulan data lokasi?',
        'location_consent_note': '(Anda tetap dapat mendaftar tanpa memberikan lokasi)',
        'manufacturer': 'Produsen',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Negara Asal',
        'country_name': 'Republik Korea (Made in Korea)',
    },
    'es': {
        'title': 'Registro de Instalación de Producto',
        'product_info': 'Información del Producto',
        'model': 'Modelo',
        'serial_number': 'Número de Serie',
        'current_installation_date': 'Fecha de Instalación Actual',
        'not_registered': 'No Registrado',
        'register_installation': 'Registrar Fecha de Instalación',
        'installation_date': 'Fecha de Instalación',
        'carrier_info': 'Información del Vehículo',
        'dealer_code': 'Código de Distribuidor',
        'register': 'Registrar Instalación',
        'success': 'La fecha de instalación se ha registrado correctamente.',
        'select_date': 'Seleccione la fecha de instalación',
        'enter_carrier': 'Ingrese información del vehículo',
        'enter_dealer': 'Ingrese código de distribuidor',
        'date_format_error': 'Ingrese la fecha en formato YYYY-MM-DD.',
        'invalid_date': 'Ingrese una fecha válida.',
        'error_occurred': 'Se produjo un error.',
        'dealer_required': 'Ingrese el código de distribuidor.',
        'verification_title': 'Verificación de Autenticidad del Producto',
        'authentic_product': 'Producto Auténtico Verificado',
        'verification_confirmed': 'Este producto ha sido verificado como auténtico.',
        'registration_info': 'Información de Registro',
        'registration_date': 'Fecha/Hora de Registro',
        'registration_location': 'Ubicación de Registro',
        'view_on_map': 'Ver en Mapa',
        'already_registered': 'Equipo ya registrado.',
        'location_consent': '¿Consiente la recopilación de datos de ubicación?',
        'location_consent_note': '(Puede registrarse sin proporcionar ubicación)',
        'manufacturer': 'Fabricante',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'País de Origen',
        'country_name': 'República de Corea (Made in Korea)',
    },
    # Vietnamese - 베트남어
    'vi': {
        'title': 'Đăng Ký Lắp Đặt Sản Phẩm',
        'product_info': 'Thông Tin Sản Phẩm',
        'model': 'Model',
        'serial_number': 'Số Serial',
        'current_installation_date': 'Ngày Lắp Đặt Hiện Tại',
        'not_registered': 'Chưa Đăng Ký',
        'register_installation': 'Đăng Ký Ngày Lắp Đặt',
        'installation_date': 'Ngày Lắp Đặt',
        'carrier_info': 'Thông Tin Xe',
        'dealer_code': 'Mã Đại Lý',
        'register': 'Đăng Ký Lắp Đặt',
        'success': 'Ngày lắp đặt đã được đăng ký thành công.',
        'select_date': 'Chọn ngày lắp đặt',
        'enter_carrier': 'Nhập thông tin xe',
        'enter_dealer': 'Nhập mã đại lý',
        'date_format_error': 'Vui lòng nhập ngày theo định dạng YYYY-MM-DD.',
        'invalid_date': 'Vui lòng nhập ngày hợp lệ.',
        'error_occurred': 'Đã xảy ra lỗi.',
        'dealer_required': 'Vui lòng nhập mã đại lý.',
        'verification_title': 'Xác Minh Tính Xác Thực Sản Phẩm',
        'authentic_product': 'Sản Phẩm Chính Hãng Đã Xác Minh',
        'verification_confirmed': 'Sản phẩm này đã được xác minh là chính hãng.',
        'registration_info': 'Thông Tin Đăng Ký',
        'registration_date': 'Ngày/Giờ Đăng Ký',
        'registration_location': 'Vị Trí Đăng Ký',
        'view_on_map': 'Xem trên Bản đồ',
        'already_registered': 'Thiết bị đã được đăng ký.',
        'location_consent': 'Bạn có đồng ý thu thập dữ liệu vị trí không?',
        'location_consent_note': '(Bạn vẫn có thể đăng ký mà không cung cấp vị trí)',
        'manufacturer': 'Nhà Sản Xuất',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Nước Sản Xuất',
        'country_name': 'Hàn Quốc (Made in Korea)',
    },
    # Thai - 태국어
    'th': {
        'title': 'ลงทะเบียนการติดตั้งผลิตภัณฑ์',
        'product_info': 'ข้อมูลผลิตภัณฑ์',
        'model': 'รุ่น',
        'serial_number': 'หมายเลขซีเรียล',
        'current_installation_date': 'วันที่ติดตั้งปัจจุบัน',
        'not_registered': 'ยังไม่ลงทะเบียน',
        'register_installation': 'ลงทะเบียนวันติดตั้ง',
        'installation_date': 'วันที่ติดตั้ง',
        'carrier_info': 'ข้อมูลรถ',
        'dealer_code': 'รหัสตัวแทนจำหน่าย',
        'register': 'ลงทะเบียนการติดตั้ง',
        'success': 'ลงทะเบียนวันติดตั้งเรียบร้อยแล้ว',
        'select_date': 'เลือกวันที่ติดตั้ง',
        'enter_carrier': 'ป้อนข้อมูลรถ',
        'enter_dealer': 'ป้อนรหัสตัวแทนจำหน่าย',
        'date_format_error': 'กรุณาป้อนวันที่ในรูปแบบ YYYY-MM-DD',
        'invalid_date': 'กรุณาป้อนวันที่ที่ถูกต้อง',
        'error_occurred': 'เกิดข้อผิดพลาด',
        'dealer_required': 'กรุณาป้อนรหัสตัวแทนจำหน่าย',
        'verification_title': 'การยืนยันความถูกต้องของผลิตภัณฑ์',
        'authentic_product': 'ผลิตภัณฑ์แท้ได้รับการยืนยัน',
        'verification_confirmed': 'ผลิตภัณฑ์นี้ได้รับการยืนยันว่าเป็นของแท้',
        'registration_info': 'ข้อมูลการลงทะเบียน',
        'registration_date': 'วันที่/เวลาลงทะเบียน',
        'registration_location': 'ตำแหน่งการลงทะเบียน',
        'view_on_map': 'ดูบนแผนที่',
        'already_registered': 'อุปกรณ์ลงทะเบียนแล้ว',
        'location_consent': 'คุณยินยอมให้เก็บข้อมูลตำแหน่งหรือไม่?',
        'location_consent_note': '(คุณยังสามารถลงทะเบียนได้โดยไม่ต้องระบุตำแหน่ง)',
        'manufacturer': 'ผู้ผลิต',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'ประเทศผู้ผลิต',
        'country_name': 'สาธารณรัฐเกาหลี (Made in Korea)',
    },
    # Arabic - 아랍어
    'ar': {
        'title': 'تسجيل تركيب المنتج',
        'product_info': 'معلومات المنتج',
        'model': 'الموديل',
        'serial_number': 'الرقم التسلسلي',
        'current_installation_date': 'تاريخ التركيب الحالي',
        'not_registered': 'غير مسجل',
        'register_installation': 'تسجيل تاريخ التركيب',
        'installation_date': 'تاريخ التركيب',
        'carrier_info': 'معلومات الناقل',
        'dealer_code': 'رمز الوكيل',
        'register': 'تسجيل التركيب',
        'success': 'تم تسجيل تاريخ التركيب بنجاح.',
        'select_date': 'اختر تاريخ التركيب',
        'enter_carrier': 'أدخل معلومات الناقل',
        'enter_dealer': 'أدخل رمز الوكيل',
        'date_format_error': 'يرجى إدخال التاريخ بصيغة YYYY-MM-DD.',
        'invalid_date': 'يرجى إدخال تاريخ صحيح.',
        'error_occurred': 'حدث خطأ.',
        'dealer_required': 'يرجى إدخال رمز الوكيل.',
        'verification_title': 'التحقق من صحة المنتج',
        'authentic_product': 'تم التحقق من المنتج الأصلي',
        'verification_confirmed': 'تم التحقق من أن هذا المنتج أصلي.',
        'registration_info': 'معلومات التسجيل',
        'registration_date': 'تاريخ/وقت التسجيل',
        'registration_location': 'موقع التسجيل',
        'view_on_map': 'عرض على الخريطة',
        'already_registered': 'الجهاز مسجل بالفعل.',
        'location_consent': 'هل توافق على جمع بيانات الموقع؟',
        'location_consent_note': '(يمكنك التسجيل بدون تقديم الموقع)',
        'manufacturer': 'الشركة المصنعة',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'بلد المنشأ',
        'country_name': 'جمهورية كوريا (Made in Korea)',
    },
    # Turkish - 터키어
    'tr': {
        'title': 'Ürün Kurulum Kaydı',
        'product_info': 'Ürün Bilgisi',
        'model': 'Model',
        'serial_number': 'Seri Numarası',
        'current_installation_date': 'Mevcut Kurulum Tarihi',
        'not_registered': 'Kayıtlı Değil',
        'register_installation': 'Kurulum Tarihini Kaydet',
        'installation_date': 'Kurulum Tarihi',
        'carrier_info': 'Araç Bilgisi',
        'dealer_code': 'Bayi Kodu',
        'register': 'Kurulumu Kaydet',
        'success': 'Kurulum tarihi başarıyla kaydedildi.',
        'select_date': 'Kurulum tarihini seçin',
        'enter_carrier': 'Araç bilgisini girin',
        'enter_dealer': 'Bayi kodunu girin',
        'date_format_error': 'Lütfen tarihi YYYY-MM-DD formatında girin.',
        'invalid_date': 'Lütfen geçerli bir tarih girin.',
        'error_occurred': 'Bir hata oluştu.',
        'dealer_required': 'Lütfen bayi kodunu girin.',
        'verification_title': 'Ürün Orijinallik Doğrulaması',
        'authentic_product': 'Orijinal Ürün Doğrulandı',
        'verification_confirmed': 'Bu ürün orijinal olarak doğrulanmıştır.',
        'registration_info': 'Kayıt Bilgileri',
        'registration_date': 'Kayıt Tarihi/Saati',
        'registration_location': 'Kayıt Konumu',
        'view_on_map': 'Haritada Görüntüle',
        'already_registered': 'Ekipman zaten kayıtlı.',
        'location_consent': 'Konum verisi toplanmasına izin veriyor musunuz?',
        'location_consent_note': '(Konum vermeden de kayıt yapabilirsiniz)',
        'manufacturer': 'Üretici',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Üretim Ülkesi',
        'country_name': 'Kore Cumhuriyeti (Made in Korea)',
    },
    # Portuguese - 포르투갈어
    'pt': {
        'title': 'Registro de Instalação do Produto',
        'product_info': 'Informações do Produto',
        'model': 'Modelo',
        'serial_number': 'Número de Série',
        'current_installation_date': 'Data de Instalação Atual',
        'not_registered': 'Não Registrado',
        'register_installation': 'Registrar Data de Instalação',
        'installation_date': 'Data de Instalação',
        'carrier_info': 'Informações do Veículo',
        'dealer_code': 'Código do Distribuidor',
        'register': 'Registrar Instalação',
        'success': 'Data de instalação registrada com sucesso.',
        'select_date': 'Selecione a data de instalação',
        'enter_carrier': 'Insira informações do veículo',
        'enter_dealer': 'Insira código do distribuidor',
        'date_format_error': 'Por favor, insira a data no formato YYYY-MM-DD.',
        'invalid_date': 'Por favor, insira uma data válida.',
        'error_occurred': 'Ocorreu um erro.',
        'dealer_required': 'Por favor, insira o código do distribuidor.',
        'verification_title': 'Verificação de Autenticidade do Produto',
        'authentic_product': 'Produto Autêntico Verificado',
        'verification_confirmed': 'Este produto foi verificado como autêntico.',
        'registration_info': 'Informações de Registro',
        'registration_date': 'Data/Hora de Registro',
        'registration_location': 'Local de Registro',
        'view_on_map': 'Ver no Mapa',
        'already_registered': 'Equipamento já registrado.',
        'location_consent': 'Você consente com a coleta de dados de localização?',
        'location_consent_note': '(Você pode se registrar sem fornecer localização)',
        'manufacturer': 'Fabricante',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'País de Origem',
        'country_name': 'República da Coreia (Made in Korea)',
    },
    # German - 독일어
    'de': {
        'title': 'Produktinstallationsregistrierung',
        'product_info': 'Produktinformationen',
        'model': 'Modell',
        'serial_number': 'Seriennummer',
        'current_installation_date': 'Aktuelles Installationsdatum',
        'not_registered': 'Nicht registriert',
        'register_installation': 'Installationsdatum registrieren',
        'installation_date': 'Installationsdatum',
        'carrier_info': 'Fahrzeuginformationen',
        'dealer_code': 'Händlercode',
        'register': 'Installation registrieren',
        'success': 'Installationsdatum wurde erfolgreich registriert.',
        'select_date': 'Installationsdatum auswählen',
        'enter_carrier': 'Fahrzeuginformationen eingeben',
        'enter_dealer': 'Händlercode eingeben',
        'date_format_error': 'Bitte geben Sie das Datum im Format YYYY-MM-DD ein.',
        'invalid_date': 'Bitte geben Sie ein gültiges Datum ein.',
        'error_occurred': 'Ein Fehler ist aufgetreten.',
        'dealer_required': 'Bitte geben Sie den Händlercode ein.',
        'verification_title': 'Produktauthentizitätsprüfung',
        'authentic_product': 'Authentisches Produkt Verifiziert',
        'verification_confirmed': 'Dieses Produkt wurde als authentisch verifiziert.',
        'registration_info': 'Registrierungsinformationen',
        'registration_date': 'Registrierungsdatum/-zeit',
        'registration_location': 'Registrierungsort',
        'view_on_map': 'Auf Karte anzeigen',
        'already_registered': 'Gerät bereits registriert.',
        'location_consent': 'Stimmen Sie der Erfassung von Standortdaten zu?',
        'location_consent_note': '(Sie können sich auch ohne Standortangabe registrieren)',
        'manufacturer': 'Hersteller',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Herkunftsland',
        'country_name': 'Republik Korea (Made in Korea)',
    },
    # French - 프랑스어
    'fr': {
        'title': "Enregistrement d'Installation du Produit",
        'product_info': 'Informations sur le Produit',
        'model': 'Modèle',
        'serial_number': 'Numéro de Série',
        'current_installation_date': "Date d'Installation Actuelle",
        'not_registered': 'Non Enregistré',
        'register_installation': "Enregistrer la Date d'Installation",
        'installation_date': "Date d'Installation",
        'carrier_info': 'Informations sur le Véhicule',
        'dealer_code': 'Code du Distributeur',
        'register': "Enregistrer l'Installation",
        'success': "La date d'installation a été enregistrée avec succès.",
        'select_date': "Sélectionnez la date d'installation",
        'enter_carrier': 'Entrez les informations du véhicule',
        'enter_dealer': 'Entrez le code du distributeur',
        'date_format_error': 'Veuillez entrer la date au format YYYY-MM-DD.',
        'invalid_date': 'Veuillez entrer une date valide.',
        'error_occurred': 'Une erreur est survenue.',
        'dealer_required': 'Veuillez entrer le code du distributeur.',
        'verification_title': "Vérification d'Authenticité du Produit",
        'authentic_product': 'Produit Authentique Vérifié',
        'verification_confirmed': 'Ce produit a été vérifié comme authentique.',
        'registration_info': "Informations d'Enregistrement",
        'registration_date': "Date/Heure d'Enregistrement",
        'registration_location': "Lieu d'Enregistrement",
        'view_on_map': 'Voir sur la Carte',
        'already_registered': 'Équipement déjà enregistré.',
        'location_consent': 'Acceptez-vous la collecte des données de localisation?',
        'location_consent_note': "(Vous pouvez vous inscrire sans fournir de localisation)",
        'manufacturer': 'Fabricant',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': "Pays d'Origine",
        'country_name': 'République de Corée (Made in Korea)',
    },
    # Italian - 이탈리아어
    'it': {
        'title': 'Registrazione Installazione Prodotto',
        'product_info': 'Informazioni Prodotto',
        'model': 'Modello',
        'serial_number': 'Numero di Serie',
        'current_installation_date': 'Data di Installazione Corrente',
        'not_registered': 'Non Registrato',
        'register_installation': 'Registra Data di Installazione',
        'installation_date': 'Data di Installazione',
        'carrier_info': 'Informazioni Veicolo',
        'dealer_code': 'Codice Rivenditore',
        'register': 'Registra Installazione',
        'success': 'La data di installazione è stata registrata con successo.',
        'select_date': 'Seleziona la data di installazione',
        'enter_carrier': 'Inserisci informazioni veicolo',
        'enter_dealer': 'Inserisci codice rivenditore',
        'date_format_error': 'Inserisci la data nel formato YYYY-MM-DD.',
        'invalid_date': 'Inserisci una data valida.',
        'error_occurred': 'Si è verificato un errore.',
        'dealer_required': 'Inserisci il codice rivenditore.',
        'verification_title': 'Verifica Autenticità Prodotto',
        'authentic_product': 'Prodotto Autentico Verificato',
        'verification_confirmed': 'Questo prodotto è stato verificato come autentico.',
        'registration_info': 'Informazioni di Registrazione',
        'registration_date': 'Data/Ora di Registrazione',
        'registration_location': 'Luogo di Registrazione',
        'view_on_map': 'Visualizza sulla Mappa',
        'already_registered': 'Attrezzatura già registrata.',
        'location_consent': 'Acconsenti alla raccolta dei dati sulla posizione?',
        'location_consent_note': '(Puoi registrarti senza fornire la posizione)',
        'manufacturer': 'Produttore',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Paese di Origine',
        'country_name': 'Repubblica di Corea (Made in Korea)',
    },
    # Dutch - 네덜란드어
    'nl': {
        'title': 'Productinstallatie Registratie',
        'product_info': 'Productinformatie',
        'model': 'Model',
        'serial_number': 'Serienummer',
        'current_installation_date': 'Huidige Installatiedatum',
        'not_registered': 'Niet Geregistreerd',
        'register_installation': 'Installatiedatum Registreren',
        'installation_date': 'Installatiedatum',
        'carrier_info': 'Voertuiginformatie',
        'dealer_code': 'Dealercode',
        'register': 'Installatie Registreren',
        'success': 'Installatiedatum is succesvol geregistreerd.',
        'select_date': 'Selecteer installatiedatum',
        'enter_carrier': 'Voer voertuiginformatie in',
        'enter_dealer': 'Voer dealercode in',
        'date_format_error': 'Voer de datum in YYYY-MM-DD formaat in.',
        'invalid_date': 'Voer een geldige datum in.',
        'error_occurred': 'Er is een fout opgetreden.',
        'dealer_required': 'Voer de dealercode in.',
        'verification_title': 'Productauthenticiteitsverificatie',
        'authentic_product': 'Authentiek Product Geverifieerd',
        'verification_confirmed': 'Dit product is geverifieerd als authentiek.',
        'registration_info': 'Registratie-informatie',
        'registration_date': 'Registratiedatum/-tijd',
        'registration_location': 'Registratielocatie',
        'view_on_map': 'Bekijk op Kaart',
        'already_registered': 'Apparatuur al geregistreerd.',
        'location_consent': 'Stemt u in met het verzamelen van locatiegegevens?',
        'location_consent_note': '(U kunt zich registreren zonder locatie op te geven)',
        'manufacturer': 'Fabrikant',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Land van Herkomst',
        'country_name': 'Republiek Korea (Made in Korea)',
    },
    # Russian - 러시아어
    'ru': {
        'title': 'Регистрация Установки Продукта',
        'product_info': 'Информация о Продукте',
        'model': 'Модель',
        'serial_number': 'Серийный Номер',
        'current_installation_date': 'Текущая Дата Установки',
        'not_registered': 'Не Зарегистрировано',
        'register_installation': 'Зарегистрировать Дату Установки',
        'installation_date': 'Дата Установки',
        'carrier_info': 'Информация о Транспортном Средстве',
        'dealer_code': 'Код Дилера',
        'register': 'Зарегистрировать Установку',
        'success': 'Дата установки успешно зарегистрирована.',
        'select_date': 'Выберите дату установки',
        'enter_carrier': 'Введите информацию о транспортном средстве',
        'enter_dealer': 'Введите код дилера',
        'date_format_error': 'Пожалуйста, введите дату в формате YYYY-MM-DD.',
        'invalid_date': 'Пожалуйста, введите действительную дату.',
        'error_occurred': 'Произошла ошибка.',
        'dealer_required': 'Пожалуйста, введите код дилера.',
        'verification_title': 'Проверка Подлинности Продукта',
        'authentic_product': 'Подлинный Продукт Подтвержден',
        'verification_confirmed': 'Этот продукт подтвержден как подлинный.',
        'registration_info': 'Информация о Регистрации',
        'registration_date': 'Дата/Время Регистрации',
        'registration_location': 'Место Регистрации',
        'view_on_map': 'Посмотреть на Карте',
        'already_registered': 'Оборудование уже зарегистрировано.',
        'location_consent': 'Вы согласны на сбор данных о местоположении?',
        'location_consent_note': '(Вы можете зарегистрироваться без указания местоположения)',
        'manufacturer': 'Производитель',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Страна Происхождения',
        'country_name': 'Республика Корея (Made in Korea)',
    },
    # Polish - 폴란드어
    'pl': {
        'title': 'Rejestracja Instalacji Produktu',
        'product_info': 'Informacje o Produkcie',
        'model': 'Model',
        'serial_number': 'Numer Seryjny',
        'current_installation_date': 'Aktualna Data Instalacji',
        'not_registered': 'Nie Zarejestrowano',
        'register_installation': 'Zarejestruj Datę Instalacji',
        'installation_date': 'Data Instalacji',
        'carrier_info': 'Informacje o Pojeździe',
        'dealer_code': 'Kod Dealera',
        'register': 'Zarejestruj Instalację',
        'success': 'Data instalacji została pomyślnie zarejestrowana.',
        'select_date': 'Wybierz datę instalacji',
        'enter_carrier': 'Wprowadź informacje o pojeździe',
        'enter_dealer': 'Wprowadź kod dealera',
        'date_format_error': 'Proszę wprowadzić datę w formacie YYYY-MM-DD.',
        'invalid_date': 'Proszę wprowadzić prawidłową datę.',
        'error_occurred': 'Wystąpił błąd.',
        'dealer_required': 'Proszę wprowadzić kod dealera.',
        'verification_title': 'Weryfikacja Autentyczności Produktu',
        'authentic_product': 'Autentyczny Produkt Zweryfikowany',
        'verification_confirmed': 'Ten produkt został zweryfikowany jako autentyczny.',
        'registration_info': 'Informacje o Rejestracji',
        'registration_date': 'Data/Czas Rejestracji',
        'registration_location': 'Lokalizacja Rejestracji',
        'view_on_map': 'Zobacz na Mapie',
        'already_registered': 'Sprzęt już zarejestrowany.',
        'location_consent': 'Czy wyrażasz zgodę na zbieranie danych o lokalizacji?',
        'location_consent_note': '(Możesz się zarejestrować bez podawania lokalizacji)',
        'manufacturer': 'Producent',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Kraj Pochodzenia',
        'country_name': 'Republika Korei (Made in Korea)',
    },
    # Czech - 체코어
    'cs': {
        'title': 'Registrace Instalace Produktu',
        'product_info': 'Informace o Produktu',
        'model': 'Model',
        'serial_number': 'Sériové Číslo',
        'current_installation_date': 'Aktuální Datum Instalace',
        'not_registered': 'Neregistrováno',
        'register_installation': 'Zaregistrovat Datum Instalace',
        'installation_date': 'Datum Instalace',
        'carrier_info': 'Informace o Vozidle',
        'dealer_code': 'Kód Dealera',
        'register': 'Zaregistrovat Instalaci',
        'success': 'Datum instalace bylo úspěšně zaregistrováno.',
        'select_date': 'Vyberte datum instalace',
        'enter_carrier': 'Zadejte informace o vozidle',
        'enter_dealer': 'Zadejte kód dealera',
        'date_format_error': 'Zadejte prosím datum ve formátu YYYY-MM-DD.',
        'invalid_date': 'Zadejte prosím platné datum.',
        'error_occurred': 'Došlo k chybě.',
        'dealer_required': 'Zadejte prosím kód dealera.',
        'verification_title': 'Ověření Pravosti Produktu',
        'authentic_product': 'Autentický Produkt Ověřen',
        'verification_confirmed': 'Tento produkt byl ověřen jako autentický.',
        'registration_info': 'Informace o Registraci',
        'registration_date': 'Datum/Čas Registrace',
        'registration_location': 'Místo Registrace',
        'view_on_map': 'Zobrazit na Mapě',
        'already_registered': 'Zařízení již zaregistrováno.',
        'location_consent': 'Souhlasíte se sběrem údajů o poloze?',
        'location_consent_note': '(Můžete se zaregistrovat bez uvedení polohy)',
        'manufacturer': 'Výrobce',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Země Původu',
        'country_name': 'Korejská republika (Made in Korea)',
    },
    # Romanian - 루마니아어
    'ro': {
        'title': 'Înregistrare Instalare Produs',
        'product_info': 'Informații Produs',
        'model': 'Model',
        'serial_number': 'Număr de Serie',
        'current_installation_date': 'Data Instalării Curente',
        'not_registered': 'Neînregistrat',
        'register_installation': 'Înregistrați Data Instalării',
        'installation_date': 'Data Instalării',
        'carrier_info': 'Informații Vehicul',
        'dealer_code': 'Cod Dealer',
        'register': 'Înregistrare Instalare',
        'success': 'Data instalării a fost înregistrată cu succes.',
        'select_date': 'Selectați data instalării',
        'enter_carrier': 'Introduceți informații vehicul',
        'enter_dealer': 'Introduceți codul dealer',
        'date_format_error': 'Vă rugăm să introduceți data în formatul YYYY-MM-DD.',
        'invalid_date': 'Vă rugăm să introduceți o dată validă.',
        'error_occurred': 'A apărut o eroare.',
        'dealer_required': 'Vă rugăm să introduceți codul dealer.',
        'verification_title': 'Verificarea Autenticității Produsului',
        'authentic_product': 'Produs Autentic Verificat',
        'verification_confirmed': 'Acest produs a fost verificat ca autentic.',
        'registration_info': 'Informații de Înregistrare',
        'registration_date': 'Data/Ora Înregistrării',
        'registration_location': 'Locația Înregistrării',
        'view_on_map': 'Vizualizare pe Hartă',
        'already_registered': 'Echipament deja înregistrat.',
        'location_consent': 'Consimțiți la colectarea datelor de locație?',
        'location_consent_note': '(Puteți înregistra fără a furniza locația)',
        'manufacturer': 'Producător',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Țara de Origine',
        'country_name': 'Republica Coreea (Made in Korea)',
    },
    # Hungarian - 헝가리어
    'hu': {
        'title': 'Termék Telepítés Regisztráció',
        'product_info': 'Termék Információ',
        'model': 'Modell',
        'serial_number': 'Sorozatszám',
        'current_installation_date': 'Jelenlegi Telepítési Dátum',
        'not_registered': 'Nem Regisztrált',
        'register_installation': 'Telepítési Dátum Regisztrálása',
        'installation_date': 'Telepítési Dátum',
        'carrier_info': 'Jármű Információ',
        'dealer_code': 'Kereskedő Kód',
        'register': 'Telepítés Regisztrálása',
        'success': 'A telepítési dátum sikeresen regisztrálva.',
        'select_date': 'Válassza ki a telepítési dátumot',
        'enter_carrier': 'Adja meg a jármű információt',
        'enter_dealer': 'Adja meg a kereskedő kódot',
        'date_format_error': 'Kérjük, adja meg a dátumot YYYY-MM-DD formátumban.',
        'invalid_date': 'Kérjük, adjon meg érvényes dátumot.',
        'error_occurred': 'Hiba történt.',
        'dealer_required': 'Kérjük, adja meg a kereskedő kódot.',
        'verification_title': 'Termék Hitelesség Ellenőrzése',
        'authentic_product': 'Hiteles Termék Ellenőrizve',
        'verification_confirmed': 'Ez a termék hitelesként lett ellenőrizve.',
        'registration_info': 'Regisztrációs Információ',
        'registration_date': 'Regisztráció Dátuma/Ideje',
        'registration_location': 'Regisztráció Helye',
        'view_on_map': 'Megtekintés a Térképen',
        'already_registered': 'A berendezés már regisztrálva van.',
        'location_consent': 'Hozzájárul a helyadatok gyűjtéséhez?',
        'location_consent_note': '(Regisztrálhat helyadatok megadása nélkül is)',
        'manufacturer': 'Gyártó',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Származási Ország',
        'country_name': 'Koreai Köztársaság (Made in Korea)',
    },
    # Ukrainian - 우크라이나어
    'uk': {
        'title': 'Реєстрація Встановлення Продукту',
        'product_info': 'Інформація про Продукт',
        'model': 'Модель',
        'serial_number': 'Серійний Номер',
        'current_installation_date': 'Поточна Дата Встановлення',
        'not_registered': 'Не Зареєстровано',
        'register_installation': 'Зареєструвати Дату Встановлення',
        'installation_date': 'Дата Встановлення',
        'carrier_info': 'Інформація про Транспортний Засіб',
        'dealer_code': 'Код Дилера',
        'register': 'Зареєструвати Встановлення',
        'success': 'Дату встановлення успішно зареєстровано.',
        'select_date': 'Виберіть дату встановлення',
        'enter_carrier': 'Введіть інформацію про транспортний засіб',
        'enter_dealer': 'Введіть код дилера',
        'date_format_error': 'Будь ласка, введіть дату у форматі YYYY-MM-DD.',
        'invalid_date': 'Будь ласка, введіть дійсну дату.',
        'error_occurred': 'Сталася помилка.',
        'dealer_required': 'Будь ласка, введіть код дилера.',
        'verification_title': 'Перевірка Автентичності Продукту',
        'authentic_product': 'Автентичний Продукт Підтверджено',
        'verification_confirmed': 'Цей продукт підтверджено як автентичний.',
        'registration_info': 'Інформація про Реєстрацію',
        'registration_date': 'Дата/Час Реєстрації',
        'registration_location': 'Місце Реєстрації',
        'view_on_map': 'Переглянути на Карті',
        'already_registered': 'Обладнання вже зареєстровано.',
        'location_consent': 'Ви погоджуєтесь на збір даних про місцезнаходження?',
        'location_consent_note': '(Ви можете зареєструватися без надання місцезнаходження)',
        'manufacturer': 'Виробник',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Країна Походження',
        'country_name': 'Республіка Корея (Made in Korea)',
    },
    # Swedish - 스웨덴어
    'sv': {
        'title': 'Produktinstallationsregistrering',
        'product_info': 'Produktinformation',
        'model': 'Modell',
        'serial_number': 'Serienummer',
        'current_installation_date': 'Nuvarande Installationsdatum',
        'not_registered': 'Inte Registrerad',
        'register_installation': 'Registrera Installationsdatum',
        'installation_date': 'Installationsdatum',
        'carrier_info': 'Fordonsinformation',
        'dealer_code': 'Återförsäljarkod',
        'register': 'Registrera Installation',
        'success': 'Installationsdatumet har registrerats framgångsrikt.',
        'select_date': 'Välj installationsdatum',
        'enter_carrier': 'Ange fordonsinformation',
        'enter_dealer': 'Ange återförsäljarkod',
        'date_format_error': 'Ange datumet i formatet YYYY-MM-DD.',
        'invalid_date': 'Ange ett giltigt datum.',
        'error_occurred': 'Ett fel uppstod.',
        'dealer_required': 'Ange återförsäljarkod.',
        'verification_title': 'Produktäkthetsverifiering',
        'authentic_product': 'Äkta Produkt Verifierad',
        'verification_confirmed': 'Denna produkt har verifierats som äkta.',
        'registration_info': 'Registreringsinformation',
        'registration_date': 'Registreringsdatum/-tid',
        'registration_location': 'Registreringsplats',
        'view_on_map': 'Visa på Karta',
        'already_registered': 'Utrustning redan registrerad.',
        'location_consent': 'Samtycker du till insamling av platsdata?',
        'location_consent_note': '(Du kan registrera utan att ange plats)',
        'manufacturer': 'Tillverkare',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Ursprungsland',
        'country_name': 'Republiken Korea (Made in Korea)',
    },
    # Danish - 덴마크어
    'da': {
        'title': 'Produktinstallationsregistrering',
        'product_info': 'Produktinformation',
        'model': 'Model',
        'serial_number': 'Serienummer',
        'current_installation_date': 'Aktuel Installationsdato',
        'not_registered': 'Ikke Registreret',
        'register_installation': 'Registrer Installationsdato',
        'installation_date': 'Installationsdato',
        'carrier_info': 'Køretøjsinformation',
        'dealer_code': 'Forhandlerkode',
        'register': 'Registrer Installation',
        'success': 'Installationsdatoen er blevet registreret.',
        'select_date': 'Vælg installationsdato',
        'enter_carrier': 'Indtast køretøjsinformation',
        'enter_dealer': 'Indtast forhandlerkode',
        'date_format_error': 'Indtast venligst datoen i formatet YYYY-MM-DD.',
        'invalid_date': 'Indtast venligst en gyldig dato.',
        'error_occurred': 'Der opstod en fejl.',
        'dealer_required': 'Indtast venligst forhandlerkode.',
        'verification_title': 'Produktægthedskontrol',
        'authentic_product': 'Ægte Produkt Verificeret',
        'verification_confirmed': 'Dette produkt er verificeret som ægte.',
        'registration_info': 'Registreringsoplysninger',
        'registration_date': 'Registreringsdato/-tid',
        'registration_location': 'Registreringssted',
        'view_on_map': 'Vis på Kort',
        'already_registered': 'Udstyr allerede registreret.',
        'location_consent': 'Giver du samtykke til indsamling af placeringsdata?',
        'location_consent_note': '(Du kan registrere uden at angive placering)',
        'manufacturer': 'Producent',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Oprindelsesland',
        'country_name': 'Republikken Korea (Made in Korea)',
    },
    # Norwegian - 노르웨이어
    'no': {
        'title': 'Produktinstallasjonsregistrering',
        'product_info': 'Produktinformasjon',
        'model': 'Modell',
        'serial_number': 'Serienummer',
        'current_installation_date': 'Nåværende Installasjonsdato',
        'not_registered': 'Ikke Registrert',
        'register_installation': 'Registrer Installasjonsdato',
        'installation_date': 'Installasjonsdato',
        'carrier_info': 'Kjøretøyinformasjon',
        'dealer_code': 'Forhandlerkode',
        'register': 'Registrer Installasjon',
        'success': 'Installasjonsdatoen er registrert.',
        'select_date': 'Velg installasjonsdato',
        'enter_carrier': 'Skriv inn kjøretøyinformasjon',
        'enter_dealer': 'Skriv inn forhandlerkode',
        'date_format_error': 'Vennligst skriv inn datoen i formatet YYYY-MM-DD.',
        'invalid_date': 'Vennligst skriv inn en gyldig dato.',
        'error_occurred': 'Det oppstod en feil.',
        'dealer_required': 'Vennligst skriv inn forhandlerkode.',
        'verification_title': 'Produktekthetskontroll',
        'authentic_product': 'Ekte Produkt Verifisert',
        'verification_confirmed': 'Dette produktet er verifisert som ekte.',
        'registration_info': 'Registreringsinformasjon',
        'registration_date': 'Registreringsdato/-tid',
        'registration_location': 'Registreringssted',
        'view_on_map': 'Vis på Kart',
        'already_registered': 'Utstyr allerede registrert.',
        'location_consent': 'Samtykker du til innsamling av posisjonsdata?',
        'location_consent_note': '(Du kan registrere uten å oppgi posisjon)',
        'manufacturer': 'Produsent',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Opprinnelsesland',
        'country_name': 'Republikken Korea (Made in Korea)',
    },
    # Finnish - 핀란드어
    'fi': {
        'title': 'Tuotteen Asennuksen Rekisteröinti',
        'product_info': 'Tuotetiedot',
        'model': 'Malli',
        'serial_number': 'Sarjanumero',
        'current_installation_date': 'Nykyinen Asennuspäivä',
        'not_registered': 'Ei Rekisteröity',
        'register_installation': 'Rekisteröi Asennuspäivä',
        'installation_date': 'Asennuspäivä',
        'carrier_info': 'Ajoneuvotiedot',
        'dealer_code': 'Jälleenmyyjäkoodi',
        'register': 'Rekisteröi Asennus',
        'success': 'Asennuspäivä on rekisteröity onnistuneesti.',
        'select_date': 'Valitse asennuspäivä',
        'enter_carrier': 'Syötä ajoneuvotiedot',
        'enter_dealer': 'Syötä jälleenmyyjäkoodi',
        'date_format_error': 'Syötä päivämäärä muodossa YYYY-MM-DD.',
        'invalid_date': 'Syötä kelvollinen päivämäärä.',
        'error_occurred': 'Tapahtui virhe.',
        'dealer_required': 'Syötä jälleenmyyjäkoodi.',
        'verification_title': 'Tuotteen Aitouden Vahvistus',
        'authentic_product': 'Aito Tuote Vahvistettu',
        'verification_confirmed': 'Tämä tuote on vahvistettu aidoksi.',
        'registration_info': 'Rekisteröintitiedot',
        'registration_date': 'Rekisteröintipäivä/-aika',
        'registration_location': 'Rekisteröintipaikka',
        'view_on_map': 'Näytä Kartalla',
        'already_registered': 'Laite on jo rekisteröity.',
        'location_consent': 'Hyväksytkö sijaintitietojen keräämisen?',
        'location_consent_note': '(Voit rekisteröityä antamatta sijaintia)',
        'manufacturer': 'Valmistaja',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Alkuperämaa',
        'country_name': 'Korean tasavalta (Made in Korea)',
    },
    # Greek - 그리스어
    'el': {
        'title': 'Εγγραφή Εγκατάστασης Προϊόντος',
        'product_info': 'Πληροφορίες Προϊόντος',
        'model': 'Μοντέλο',
        'serial_number': 'Σειριακός Αριθμός',
        'current_installation_date': 'Τρέχουσα Ημερομηνία Εγκατάστασης',
        'not_registered': 'Μη Εγγεγραμμένο',
        'register_installation': 'Εγγραφή Ημερομηνίας Εγκατάστασης',
        'installation_date': 'Ημερομηνία Εγκατάστασης',
        'carrier_info': 'Πληροφορίες Οχήματος',
        'dealer_code': 'Κωδικός Αντιπροσώπου',
        'register': 'Εγγραφή Εγκατάστασης',
        'success': 'Η ημερομηνία εγκατάστασης καταχωρήθηκε επιτυχώς.',
        'select_date': 'Επιλέξτε ημερομηνία εγκατάστασης',
        'enter_carrier': 'Εισαγάγετε πληροφορίες οχήματος',
        'enter_dealer': 'Εισαγάγετε κωδικό αντιπροσώπου',
        'date_format_error': 'Εισαγάγετε την ημερομηνία σε μορφή YYYY-MM-DD.',
        'invalid_date': 'Εισαγάγετε μια έγκυρη ημερομηνία.',
        'error_occurred': 'Παρουσιάστηκε σφάλμα.',
        'dealer_required': 'Εισαγάγετε τον κωδικό αντιπροσώπου.',
        'verification_title': 'Επαλήθευση Γνησιότητας Προϊόντος',
        'authentic_product': 'Γνήσιο Προϊόν Επαληθευμένο',
        'verification_confirmed': 'Αυτό το προϊόν έχει επαληθευτεί ως γνήσιο.',
        'registration_info': 'Πληροφορίες Εγγραφής',
        'registration_date': 'Ημερομηνία/Ώρα Εγγραφής',
        'registration_location': 'Τοποθεσία Εγγραφής',
        'view_on_map': 'Προβολή στον Χάρτη',
        'already_registered': 'Ο εξοπλισμός είναι ήδη εγγεγραμμένος.',
        'location_consent': 'Συναινείτε στη συλλογή δεδομένων τοποθεσίας;',
        'location_consent_note': '(Μπορείτε να εγγραφείτε χωρίς να παρέχετε τοποθεσία)',
        'manufacturer': 'Κατασκευαστής',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Χώρα Προέλευσης',
        'country_name': 'Δημοκρατία της Κορέας (Made in Korea)',
    },
    # Persian/Farsi - 페르시아어
    'fa': {
        'title': 'ثبت نصب محصول',
        'product_info': 'اطلاعات محصول',
        'model': 'مدل',
        'serial_number': 'شماره سریال',
        'current_installation_date': 'تاریخ نصب فعلی',
        'not_registered': 'ثبت نشده',
        'register_installation': 'ثبت تاریخ نصب',
        'installation_date': 'تاریخ نصب',
        'carrier_info': 'اطلاعات خودرو',
        'dealer_code': 'کد نمایندگی',
        'register': 'ثبت نصب',
        'success': 'تاریخ نصب با موفقیت ثبت شد.',
        'select_date': 'تاریخ نصب را انتخاب کنید',
        'enter_carrier': 'اطلاعات خودرو را وارد کنید',
        'enter_dealer': 'کد نمایندگی را وارد کنید',
        'date_format_error': 'لطفاً تاریخ را در قالب YYYY-MM-DD وارد کنید.',
        'invalid_date': 'لطفاً یک تاریخ معتبر وارد کنید.',
        'error_occurred': 'خطایی رخ داده است.',
        'dealer_required': 'لطفاً کد نمایندگی را وارد کنید.',
        'verification_title': 'تأیید اصالت محصول',
        'authentic_product': 'محصول اصل تأیید شد',
        'verification_confirmed': 'این محصول به عنوان اصل تأیید شده است.',
        'registration_info': 'اطلاعات ثبت',
        'registration_date': 'تاریخ/زمان ثبت',
        'registration_location': 'موقعیت ثبت',
        'view_on_map': 'مشاهده روی نقشه',
        'already_registered': 'تجهیزات قبلاً ثبت شده است.',
        'location_consent': 'آیا با جمع‌آوری اطلاعات موقعیت مکانی موافقید؟',
        'location_consent_note': '(می‌توانید بدون ارائه موقعیت ثبت‌نام کنید)',
        'manufacturer': 'سازنده',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'کشور مبدأ',
        'country_name': 'جمهوری کره (Made in Korea)',
    },
    # Bulgarian - 불가리아어
    'bg': {
        'title': 'Регистрация на Монтаж на Продукт',
        'product_info': 'Информация за Продукта',
        'model': 'Модел',
        'serial_number': 'Сериен Номер',
        'current_installation_date': 'Текуща Дата на Монтаж',
        'not_registered': 'Не е Регистрирано',
        'register_installation': 'Регистрирай Дата на Монтаж',
        'installation_date': 'Дата на Монтаж',
        'carrier_info': 'Информация за Превозното Средство',
        'dealer_code': 'Код на Дилъра',
        'register': 'Регистрирай Монтаж',
        'success': 'Датата на монтаж е регистрирана успешно.',
        'select_date': 'Изберете дата на монтаж',
        'enter_carrier': 'Въведете информация за превозното средство',
        'enter_dealer': 'Въведете код на дилъра',
        'date_format_error': 'Моля, въведете датата във формат YYYY-MM-DD.',
        'invalid_date': 'Моля, въведете валидна дата.',
        'error_occurred': 'Възникна грешка.',
        'dealer_required': 'Моля, въведете код на дилъра.',
        'verification_title': 'Проверка на Автентичността на Продукта',
        'authentic_product': 'Автентичен Продукт Потвърден',
        'verification_confirmed': 'Този продукт е потвърден като автентичен.',
        'registration_info': 'Информация за Регистрацията',
        'registration_date': 'Дата/Час на Регистрация',
        'registration_location': 'Местоположение на Регистрация',
        'view_on_map': 'Виж на Картата',
        'already_registered': 'Оборудването вече е регистрирано.',
        'location_consent': 'Съгласни ли сте със събирането на данни за местоположение?',
        'location_consent_note': '(Можете да се регистрирате без да предоставяте местоположение)',
        'manufacturer': 'Производител',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Страна на Произход',
        'country_name': 'Република Корея (Made in Korea)',
    },
    # Serbian - 세르비아어
    'sr': {
        'title': 'Регистрација Инсталације Производа',
        'product_info': 'Информације о Производу',
        'model': 'Модел',
        'serial_number': 'Серијски Број',
        'current_installation_date': 'Тренутни Датум Инсталације',
        'not_registered': 'Није Регистровано',
        'register_installation': 'Региструј Датум Инсталације',
        'installation_date': 'Датум Инсталације',
        'carrier_info': 'Информације о Возилу',
        'dealer_code': 'Код Дилера',
        'register': 'Региструј Инсталацију',
        'success': 'Датум инсталације је успешно регистрован.',
        'select_date': 'Изаберите датум инсталације',
        'enter_carrier': 'Унесите информације о возилу',
        'enter_dealer': 'Унесите код дилера',
        'date_format_error': 'Молимо унесите датум у формату YYYY-MM-DD.',
        'invalid_date': 'Молимо унесите важећи датум.',
        'error_occurred': 'Дошло је до грешке.',
        'dealer_required': 'Молимо унесите код дилера.',
        'verification_title': 'Верификација Аутентичности Производа',
        'authentic_product': 'Аутентичан Производ Верификован',
        'verification_confirmed': 'Овај производ је верификован као аутентичан.',
        'registration_info': 'Информације о Регистрацији',
        'registration_date': 'Датум/Време Регистрације',
        'registration_location': 'Локација Регистрације',
        'view_on_map': 'Прикажи на Мапи',
        'already_registered': 'Опрема је већ регистрована.',
        'location_consent': 'Да ли пристајете на прикупљање података о локацији?',
        'location_consent_note': '(Можете се регистровати без навођења локације)',
        'manufacturer': 'Произвођач',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Земља Порекла',
        'country_name': 'Република Кореја (Made in Korea)',
    },
    # Croatian - 크로아티아어
    'hr': {
        'title': 'Registracija Instalacije Proizvoda',
        'product_info': 'Informacije o Proizvodu',
        'model': 'Model',
        'serial_number': 'Serijski Broj',
        'current_installation_date': 'Trenutni Datum Instalacije',
        'not_registered': 'Nije Registrirano',
        'register_installation': 'Registriraj Datum Instalacije',
        'installation_date': 'Datum Instalacije',
        'carrier_info': 'Informacije o Vozilu',
        'dealer_code': 'Kod Dilera',
        'register': 'Registriraj Instalaciju',
        'success': 'Datum instalacije je uspješno registriran.',
        'select_date': 'Odaberite datum instalacije',
        'enter_carrier': 'Unesite informacije o vozilu',
        'enter_dealer': 'Unesite kod dilera',
        'date_format_error': 'Molimo unesite datum u formatu YYYY-MM-DD.',
        'invalid_date': 'Molimo unesite valjani datum.',
        'error_occurred': 'Došlo je do pogreške.',
        'dealer_required': 'Molimo unesite kod dilera.',
        'verification_title': 'Verifikacija Autentičnosti Proizvoda',
        'authentic_product': 'Autentičan Proizvod Verificiran',
        'verification_confirmed': 'Ovaj proizvod je verificiran kao autentičan.',
        'registration_info': 'Informacije o Registraciji',
        'registration_date': 'Datum/Vrijeme Registracije',
        'registration_location': 'Lokacija Registracije',
        'view_on_map': 'Prikaži na Karti',
        'already_registered': 'Oprema je već registrirana.',
        'location_consent': 'Pristajete li na prikupljanje podataka o lokaciji?',
        'location_consent_note': '(Možete se registrirati bez navođenja lokacije)',
        'manufacturer': 'Proizvođač',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Zemlja Podrijetla',
        'country_name': 'Republika Koreja (Made in Korea)',
    },
    # Slovak - 슬로바키아어
    'sk': {
        'title': 'Registrácia Inštalácie Produktu',
        'product_info': 'Informácie o Produkte',
        'model': 'Model',
        'serial_number': 'Sériové Číslo',
        'current_installation_date': 'Aktuálny Dátum Inštalácie',
        'not_registered': 'Neregistrované',
        'register_installation': 'Zaregistrovať Dátum Inštalácie',
        'installation_date': 'Dátum Inštalácie',
        'carrier_info': 'Informácie o Vozidle',
        'dealer_code': 'Kód Dealera',
        'register': 'Zaregistrovať Inštaláciu',
        'success': 'Dátum inštalácie bol úspešne zaregistrovaný.',
        'select_date': 'Vyberte dátum inštalácie',
        'enter_carrier': 'Zadajte informácie o vozidle',
        'enter_dealer': 'Zadajte kód dealera',
        'date_format_error': 'Prosím, zadajte dátum vo formáte YYYY-MM-DD.',
        'invalid_date': 'Prosím, zadajte platný dátum.',
        'error_occurred': 'Vyskytla sa chyba.',
        'dealer_required': 'Prosím, zadajte kód dealera.',
        'verification_title': 'Overenie Autenticity Produktu',
        'authentic_product': 'Autentický Produkt Overený',
        'verification_confirmed': 'Tento produkt bol overený ako autentický.',
        'registration_info': 'Informácie o Registrácii',
        'registration_date': 'Dátum/Čas Registrácie',
        'registration_location': 'Miesto Registrácie',
        'view_on_map': 'Zobraziť na Mape',
        'already_registered': 'Zariadenie je už zaregistrované.',
        'location_consent': 'Súhlasíte so zhromažďovaním údajov o polohe?',
        'location_consent_note': '(Môžete sa zaregistrovať bez uvedenia polohy)',
        'manufacturer': 'Výrobca',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Krajina Pôvodu',
        'country_name': 'Kórejská republika (Made in Korea)',
    },
    # Slovenian - 슬로베니아어
    'sl': {
        'title': 'Registracija Namestitve Izdelka',
        'product_info': 'Informacije o Izdelku',
        'model': 'Model',
        'serial_number': 'Serijska Številka',
        'current_installation_date': 'Trenutni Datum Namestitve',
        'not_registered': 'Ni Registrirano',
        'register_installation': 'Registriraj Datum Namestitve',
        'installation_date': 'Datum Namestitve',
        'carrier_info': 'Informacije o Vozilu',
        'dealer_code': 'Koda Trgovca',
        'register': 'Registriraj Namestitev',
        'success': 'Datum namestitve je bil uspešno registriran.',
        'select_date': 'Izberite datum namestitve',
        'enter_carrier': 'Vnesite informacije o vozilu',
        'enter_dealer': 'Vnesite kodo trgovca',
        'date_format_error': 'Prosimo, vnesite datum v obliki YYYY-MM-DD.',
        'invalid_date': 'Prosimo, vnesite veljaven datum.',
        'error_occurred': 'Prišlo je do napake.',
        'dealer_required': 'Prosimo, vnesite kodo trgovca.',
        'verification_title': 'Preverjanje Pristnosti Izdelka',
        'authentic_product': 'Pristen Izdelek Preverjen',
        'verification_confirmed': 'Ta izdelek je bil preverjen kot pristen.',
        'registration_info': 'Informacije o Registraciji',
        'registration_date': 'Datum/Čas Registracije',
        'registration_location': 'Lokacija Registracije',
        'view_on_map': 'Prikaži na Zemljevidu',
        'already_registered': 'Oprema je že registrirana.',
        'location_consent': 'Ali se strinjate z zbiranjem podatkov o lokaciji?',
        'location_consent_note': '(Registrirate se lahko brez navedbe lokacije)',
        'manufacturer': 'Proizvajalec',
        'manufacturer_name': 'SOOSAN CEBOTICS',
        'country_of_origin': 'Država Izvora',
        'country_name': 'Republika Koreja (Made in Korea)',
    },
}

# Country to language mapping (70+ countries with Korean names, English names, and ISO codes)
COUNTRY_LANG_MAP = {
    # === 동아시아 (East Asia) ===
    # Korean
    '한국': 'ko', 'Korea': 'ko', 'South Korea': 'ko', 'KR': 'ko', '대한민국': 'ko',
    # Japanese
    '일본': 'ja', 'Japan': 'ja', 'JP': 'ja',
    # Chinese
    '중국': 'zh', 'China': 'zh', 'CN': 'zh',
    '대만': 'zh', 'Taiwan': 'zh', 'TW': 'zh',
    '홍콩': 'zh', 'Hong Kong': 'zh', 'HK': 'zh',
    # Mongolian (using English)
    '몽골': 'en', 'Mongolia': 'en', 'MN': 'en',

    # === 동남아시아 (Southeast Asia) ===
    # Indonesian
    '인도네시아': 'id', 'Indonesia': 'id',
    # Vietnamese
    '베트남': 'vi', 'Vietnam': 'vi', 'VN': 'vi',
    # Thai
    '태국': 'th', 'Thailand': 'th', 'TH': 'th',
    # English-speaking SEA
    '필리핀': 'en', 'Philippines': 'en', 'PH': 'en',
    '말레이시아': 'en', 'Malaysia': 'en', 'MY': 'en',
    '싱가포르': 'en', 'Singapore': 'en', 'SG': 'en',
    '미얀마': 'en', 'Myanmar': 'en', 'MM': 'en',
    '캄보디아': 'en', 'Cambodia': 'en', 'KH': 'en',
    '라오스': 'en', 'Laos': 'en', 'LA': 'en',

    # === 남아시아 (South Asia) ===
    '인도': 'en', 'India': 'en', 'IN': 'en',
    '방글라데시': 'en', 'Bangladesh': 'en', 'BD': 'en',
    '파키스탄': 'en', 'Pakistan': 'en', 'PK': 'en',
    '스리랑카': 'en', 'Sri Lanka': 'en', 'LK': 'en',
    '네팔': 'en', 'Nepal': 'en', 'NP': 'en',

    # === 중동 (Middle East) ===
    # Arabic-speaking
    '사우디아라비아': 'ar', 'Saudi Arabia': 'ar', 'SA': 'ar',
    '아랍에미리트': 'ar', 'UAE': 'ar', 'United Arab Emirates': 'ar', 'AE': 'ar',
    '카타르': 'ar', 'Qatar': 'ar', 'QA': 'ar',
    '쿠웨이트': 'ar', 'Kuwait': 'ar', 'KW': 'ar',
    '오만': 'ar', 'Oman': 'ar', 'OM': 'ar',
    '바레인': 'ar', 'Bahrain': 'ar', 'BH': 'ar',
    '이라크': 'ar', 'Iraq': 'ar', 'IQ': 'ar',
    '요르단': 'ar', 'Jordan': 'ar', 'JO': 'ar',
    '레바논': 'ar', 'Lebanon': 'ar', 'LB': 'ar',
    # Persian
    '이란': 'fa', 'Iran': 'fa', 'IR': 'fa',
    # Turkish
    '터키': 'tr', 'Turkey': 'tr', 'Turkiye': 'tr', 'TR': 'tr',
    # English (Israel)
    '이스라엘': 'en', 'Israel': 'en', 'IL': 'en',

    # === 오세아니아 (Oceania) ===
    '호주': 'en', 'Australia': 'en', 'AU': 'en',
    '뉴질랜드': 'en', 'New Zealand': 'en', 'NZ': 'en',
    '파푸아뉴기니': 'en', 'Papua New Guinea': 'en', 'PG': 'en',

    # === 북미 (North America) ===
    '미국': 'en', 'USA': 'en', 'United States': 'en', 'US': 'en',
    '캐나다': 'en', 'Canada': 'en', 'CA': 'en',

    # === 중남미 (Latin America) - Spanish ===
    '멕시코': 'es', 'Mexico': 'es', 'MX': 'es',
    '아르헨티나': 'es', 'Argentina': 'es',
    '칠레': 'es', 'Chile': 'es', 'CL': 'es',
    '콜롬비아': 'es', 'Colombia': 'es', 'CO': 'es',
    '페루': 'es', 'Peru': 'es', 'PE': 'es',
    '에콰도르': 'es', 'Ecuador': 'es', 'EC': 'es',
    '베네수엘라': 'es', 'Venezuela': 'es', 'VE': 'es',
    '볼리비아': 'es', 'Bolivia': 'es', 'BO': 'es',
    '파라과이': 'es', 'Paraguay': 'es', 'PY': 'es',
    '우루과이': 'es', 'Uruguay': 'es', 'UY': 'es',
    '파나마': 'es', 'Panama': 'es', 'PA': 'es',
    '코스타리카': 'es', 'Costa Rica': 'es', 'CR': 'es',
    '과테말라': 'es', 'Guatemala': 'es', 'GT': 'es',
    '도미니카공화국': 'es', 'Dominican Republic': 'es', 'DO': 'es',
    '스페인': 'es', 'Spain': 'es',
    # Portuguese (Brazil, Portugal)
    '브라질': 'pt', 'Brazil': 'pt', 'BR': 'pt',
    '포르투갈': 'pt', 'Portugal': 'pt', 'PT': 'pt',

    # === 서유럽 (Western Europe) ===
    '영국': 'en', 'UK': 'en', 'United Kingdom': 'en', 'GB': 'en',
    '아일랜드': 'en', 'Ireland': 'en', 'IE': 'en',
    # German-speaking
    '독일': 'de', 'Germany': 'de', 'DE': 'de',
    '오스트리아': 'de', 'Austria': 'de', 'AT': 'de',
    '스위스': 'de', 'Switzerland': 'de', 'CH': 'de',
    # French-speaking
    '프랑스': 'fr', 'France': 'fr', 'FR': 'fr',
    '벨기에': 'fr', 'Belgium': 'fr', 'BE': 'fr',
    # Italian
    '이탈리아': 'it', 'Italy': 'it', 'IT': 'it',
    # Dutch
    '네덜란드': 'nl', 'Netherlands': 'nl', 'NL': 'nl',
    # Nordic countries
    '스웨덴': 'sv', 'Sweden': 'sv', 'SE': 'sv',
    '노르웨이': 'no', 'Norway': 'no', 'NO': 'no',
    '덴마크': 'da', 'Denmark': 'da', 'DK': 'da',
    '핀란드': 'fi', 'Finland': 'fi', 'FI': 'fi',
    # Greek
    '그리스': 'el', 'Greece': 'el', 'GR': 'el',

    # === 동유럽 (Eastern Europe) ===
    # Russian-speaking
    '러시아': 'ru', 'Russia': 'ru', 'RU': 'ru',
    '카자흐스탄': 'ru', 'Kazakhstan': 'ru', 'KZ': 'ru',
    '우즈베키스탄': 'ru', 'Uzbekistan': 'ru', 'UZ': 'ru',
    # Polish
    '폴란드': 'pl', 'Poland': 'pl', 'PL': 'pl',
    # Czech
    '체코': 'cs', 'Czech Republic': 'cs', 'Czechia': 'cs', 'CZ': 'cs',
    # Romanian
    '루마니아': 'ro', 'Romania': 'ro', 'RO': 'ro',
    # Hungarian
    '헝가리': 'hu', 'Hungary': 'hu', 'HU': 'hu',
    # Ukrainian
    '우크라이나': 'uk', 'Ukraine': 'uk', 'UA': 'uk',
    # Bulgarian
    '불가리아': 'bg', 'Bulgaria': 'bg', 'BG': 'bg',
    # Serbian
    '세르비아': 'sr', 'Serbia': 'sr', 'RS': 'sr',
    # Croatian
    '크로아티아': 'hr', 'Croatia': 'hr', 'HR': 'hr',
    # Slovak
    '슬로바키아': 'sk', 'Slovakia': 'sk', 'SK': 'sk',
    # Slovenian
    '슬로베니아': 'sl', 'Slovenia': 'sl', 'SI': 'sl',

    # === 아프리카 (Africa) ===
    # English-speaking Africa
    '남아프리카공화국': 'en', 'South Africa': 'en', 'ZA': 'en',
    '나이지리아': 'en', 'Nigeria': 'en', 'NG': 'en',
    '가나': 'en', 'Ghana': 'en', 'GH': 'en',
    '케냐': 'en', 'Kenya': 'en', 'KE': 'en',
    '탄자니아': 'en', 'Tanzania': 'en', 'TZ': 'en',
    '에티오피아': 'en', 'Ethiopia': 'en', 'ET': 'en',
    '잠비아': 'en', 'Zambia': 'en', 'ZM': 'en',
    '짐바브웨': 'en', 'Zimbabwe': 'en', 'ZW': 'en',
    '보츠와나': 'en', 'Botswana': 'en', 'BW': 'en',
    # Arabic-speaking Africa
    '이집트': 'ar', 'Egypt': 'ar', 'EG': 'ar',
    '모로코': 'ar', 'Morocco': 'ar', 'MA': 'ar',
    '알제리': 'ar', 'Algeria': 'ar', 'DZ': 'ar',
    '지부티': 'ar', 'Djibouti': 'ar', 'DJ': 'ar',
    # French-speaking Africa
    '콩고': 'fr', 'Congo': 'fr', 'CD': 'fr',
    # Portuguese-speaking Africa
    '앙골라': 'pt', 'Angola': 'pt', 'AO': 'pt',
    '모잠비크': 'pt', 'Mozambique': 'pt', 'MZ': 'pt',
}


def get_language(equipment, req):
    """Determine language based on browser Accept-Language header only.
    Default: English
    """
    # Browser language setting only (all 26 supported languages)
    supported_langs = [
        'en', 'ko', 'ja', 'zh', 'id', 'es',  # Original 6
        'vi', 'th', 'ar', 'tr', 'pt', 'de', 'fr', 'it', 'nl',  # New languages
        'ru', 'pl', 'cs', 'ro', 'hu', 'uk', 'sv', 'da', 'no', 'fi', 'el',  # More new
        'fa', 'bg', 'sr', 'hr', 'sk', 'sl'  # Eastern European + Persian
    ]
    browser_lang = req.accept_languages.best_match(supported_langs)
    if browser_lang:
        return browser_lang

    # Default: English
    return 'en'


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/scan/<token>')
def scan(token):
    try:
        # 토큰으로 장비 정보 조회 (GPS 및 등록 타임스탬프 포함)
        result = supabase.table('equipment').select(
            'id, model, unit_number, installation_date, '
            'product_code, product_name, customer, created_at, carrier_info, dealer_code, '
            'registration_latitude, registration_longitude, registration_timestamp'
        ).eq('access_token', token).execute()

        if not result.data:
            return "Invalid QR code.", 404

        equipment = result.data[0]

        # 언어 결정 (브라우저 설정 기반)
        lang = get_language(equipment, request)
        t = TRANSLATIONS.get(lang, TRANSLATIONS['en'])

        # 오늘 날짜를 템플릿에 전달
        today = datetime.now().strftime('%Y-%m-%d')

        # 이미 장착일이 등록된 경우 정품 인증 페이지로 렌더링
        if equipment.get('installation_date'):
            dealer_code = equipment.get('dealer_code', '')
            dealer_name = DEALER_MAP.get(dealer_code, dealer_code)
            return render_template('verification.html', equipment=equipment, lang=lang, t=t, dealer_name=dealer_name)

        # 미등록인 경우 등록 폼 표시
        dealer_map_json = json.dumps(DEALER_MAP, ensure_ascii=False)
        return render_template('scan.html', equipment=equipment, today=today, lang=lang, t=t, dealer_map_json=dealer_map_json)

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
        latitude = request.form.get('latitude', '')
        longitude = request.form.get('longitude', '')

        if not equipment_id or not installation_date:
            return jsonify({'error': '필수 정보가 누락되었습니다.'}), 400

        if not dealer_code:
            return jsonify({'error': '딜러 코드를 입력해주세요.'}), 400

        # 재등록 방지: 이미 등록된 장비인지 확인
        existing = supabase.table('equipment').select('installation_date').eq('id', equipment_id).execute()
        if existing.data and existing.data[0].get('installation_date'):
            return jsonify({'error': '이미 등록된 장비입니다.'}), 400

        # 업데이트 데이터 준비
        update_data = {
            'installation_date': installation_date,
            'carrier_info': carrier_info,
            'dealer_code': dealer_code,
            'registration_timestamp': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        # GPS 좌표 처리 (명시적 동의 시에만 저장, IP fallback 없음)
        if latitude and longitude:
            try:
                update_data['registration_latitude'] = float(latitude)
                update_data['registration_longitude'] = float(longitude)
            except ValueError:
                pass  # 위치 없이 진행

        # 장착일 및 추가 정보 업데이트
        supabase.table('equipment').update(update_data).eq('id', equipment_id).execute()

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

        # 리드타임 분석 (장착일 - 등록일 차이)
        lead_times = []
        lead_time_ranges = {'0-7일': 0, '8-14일': 0, '15-30일': 0, '31-60일': 0, '60일+': 0}

        for eq in completed:
            if eq.get('installation_date') and eq.get('created_at'):
                # created_at 사용
                created_str = eq.get('created_at')
                install_str = eq['installation_date']

                if created_str:
                    # created_at을 날짜로 변환 (시간 무시)
                    if isinstance(created_str, str):
                        created_date = datetime.strptime(created_str[:10], '%Y-%m-%d').date()
                    else:
                        created_date = created_str.date() if hasattr(created_str, 'date') else created_str

                    # installation_date를 날짜로 변환
                    if isinstance(install_str, str):
                        install_date = datetime.strptime(install_str[:10], '%Y-%m-%d').date()
                    else:
                        install_date = install_str.date() if hasattr(install_str, 'date') else install_str

                    # 날짜 차이 계산 (시간 무시): 장착일 - 등록일
                    lead_time = (install_date - created_date).days
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
