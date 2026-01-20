"""
ERP Database (MS SQL Server) Connection Module
UNIERP 시스템과 연동하기 위한 MS SQL Server 연결 모듈
"""

import os
from typing import List, Dict, Optional

# pyodbc는 선택적 의존성 - 설치되어 있지 않으면 ERP 기능 비활성화
try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False
    pyodbc = None


class ERPDB:
    """MS SQL Server ERP 데이터베이스 연결 클래스"""

    def __init__(self):
        """환경 변수에서 연결 정보를 로드하여 연결 문자열 생성"""
        self.server = os.getenv('ERP_DB_HOST', '')
        self.database = os.getenv('ERP_DB_NAME', '')
        self.username = os.getenv('ERP_DB_USER', '')
        self.password = os.getenv('ERP_DB_PASSWORD', '')

        # ODBC Driver 설정 (환경에 따라 변경 가능)
        self.driver = os.getenv('ERP_DB_DRIVER', 'ODBC Driver 17 for SQL Server')

        self.conn_str = (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
            f"PWD={self.password};"
            f"TrustServerCertificate=yes;"
        )

    def _get_connection(self) -> pyodbc.Connection:
        """데이터베이스 연결 생성"""
        return pyodbc.connect(self.conn_str)

    def is_configured(self) -> bool:
        """ERP DB 연결이 설정되어 있는지 확인"""
        if not PYODBC_AVAILABLE:
            return False
        return bool(self.server and self.database and self.username)

    def test_connection(self) -> bool:
        """데이터베이스 연결 테스트"""
        try:
            conn = self._get_connection()
            conn.close()
            return True
        except Exception as e:
            print(f"ERP DB connection test failed: {e}")
            return False

    def get_products_by_ids(self, product_ids: List[str]) -> List[Dict]:
        """
        ERP에서 제품 ID 목록으로 제품 정보 조회

        Args:
            product_ids: ERP 제품 ID 목록

        Returns:
            제품 정보 딕셔너리 리스트

        Note:
            TODO: 실제 ERP 테이블명과 필드명은 비젠트로 UNIERP 스키마에 맞게 수정 필요
        """
        if not product_ids:
            return []

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 파라미터 플레이스홀더 생성
            placeholders = ','.join(['?' for _ in product_ids])

            # TODO: 실제 ERP 테이블명/필드명으로 변경 필요
            # 예시 쿼리 - 실제 스키마에 맞게 수정 필요
            query = f"""
                SELECT
                    product_id,
                    model,
                    unit_number,
                    order_number,
                    export_country,
                    shipment_date
                FROM shipment_products
                WHERE product_id IN ({placeholders})
            """

            cursor.execute(query, product_ids)

            columns = [column[0] for column in cursor.description]
            results = []

            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))

            cursor.close()
            conn.close()

            return results

        except Exception as e:
            print(f"Error fetching products from ERP: {e}")
            raise

    def get_products_by_shipment(self, shipment_id: str) -> List[Dict]:
        """
        출하 ID로 해당 출하에 포함된 모든 제품 조회

        Args:
            shipment_id: 출하 ID

        Returns:
            제품 정보 딕셔너리 리스트
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # TODO: 실제 ERP 테이블명/필드명으로 변경 필요
            query = """
                SELECT
                    product_id,
                    model,
                    unit_number,
                    order_number,
                    export_country,
                    shipment_date
                FROM shipment_products
                WHERE shipment_id = ?
            """

            cursor.execute(query, (shipment_id,))

            columns = [column[0] for column in cursor.description]
            results = []

            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))

            cursor.close()
            conn.close()

            return results

        except Exception as e:
            print(f"Error fetching shipment products from ERP: {e}")
            raise

    def save_installation_info(self, data: Dict) -> bool:
        """
        장착 정보를 ERP 데이터베이스에 저장

        Args:
            data: 장착 정보 딕셔너리
                - model: 기종
                - unit_number: 호기
                - installation_date: 장착일
                - dealer_code: 딜러 코드
                - carrier_info: 대차 정보 (선택)
                - latitude: 위도 (선택)
                - longitude: 경도 (선택)

        Returns:
            성공 여부
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # TODO: 실제 ERP 테이블명/필드명으로 변경 필요
            # 장착 정보 저장 테이블이 별도로 있다면 INSERT
            # 기존 제품 테이블에 업데이트한다면 UPDATE

            # 예시: 장착 정보 테이블에 INSERT
            query = """
                INSERT INTO installation_records (
                    model,
                    unit_number,
                    installation_date,
                    dealer_code,
                    carrier_info,
                    latitude,
                    longitude,
                    registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, GETDATE())
            """

            cursor.execute(query, (
                data.get('model'),
                data.get('unit_number'),
                data.get('installation_date'),
                data.get('dealer_code'),
                data.get('carrier_info', ''),
                data.get('latitude'),
                data.get('longitude')
            ))

            conn.commit()
            cursor.close()
            conn.close()

            return True

        except Exception as e:
            print(f"Error saving installation info to ERP: {e}")
            return False

    def update_product_installation(self, model: str, unit_number: str,
                                     installation_date: str, dealer_code: str) -> bool:
        """
        기존 제품 레코드의 장착 정보 업데이트

        Args:
            model: 기종
            unit_number: 호기
            installation_date: 장착일
            dealer_code: 딜러 코드

        Returns:
            성공 여부
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # TODO: 실제 ERP 테이블명/필드명으로 변경 필요
            query = """
                UPDATE shipment_products
                SET
                    installation_date = ?,
                    dealer_code = ?,
                    updated_at = GETDATE()
                WHERE model = ? AND unit_number = ?
            """

            cursor.execute(query, (
                installation_date,
                dealer_code,
                model,
                unit_number
            ))

            affected_rows = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()

            return affected_rows > 0

        except Exception as e:
            print(f"Error updating product installation in ERP: {e}")
            return False


# 모듈 레벨 인스턴스 (선택적 사용)
def get_erp_db() -> Optional[ERPDB]:
    """
    ERP DB 인스턴스 반환 (설정되어 있는 경우에만)

    Returns:
        ERPDB 인스턴스 또는 None (pyodbc 미설치 또는 미설정 시)
    """
    if not PYODBC_AVAILABLE:
        return None
    erp = ERPDB()
    if erp.is_configured():
        return erp
    return None


def is_erp_available() -> bool:
    """ERP 연동 기능 사용 가능 여부 확인"""
    return PYODBC_AVAILABLE and get_erp_db() is not None
