-- Supabase (PostgreSQL) 용 스키마
CREATE TABLE IF NOT EXISTS equipment (
    id SERIAL PRIMARY KEY,
    model VARCHAR(100) NOT NULL,
    unit_number VARCHAR(100) NOT NULL,
    access_token VARCHAR(64) UNIQUE NOT NULL,
    order_number VARCHAR(100),
    export_country VARCHAR(100),
    qr_registered_date DATE,
    shipment_date DATE,
    installation_date DATE,
    carrier_info VARCHAR(200),
    dealer_code VARCHAR(100),
    registration_latitude DECIMAL(10, 8),
    registration_longitude DECIMAL(11, 8),
    registration_timestamp TIMESTAMPTZ,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_model_unit UNIQUE (model, unit_number)
);

-- GPS 위치 및 등록 타임스탬프 컬럼 추가 (기존 테이블 마이그레이션용)
-- ALTER TABLE equipment
-- ADD COLUMN IF NOT EXISTS registration_latitude DECIMAL(10, 8),
-- ADD COLUMN IF NOT EXISTS registration_longitude DECIMAL(11, 8),
-- ADD COLUMN IF NOT EXISTS registration_timestamp TIMESTAMPTZ;

-- 토큰 조회 성능을 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_equipment_token ON equipment(access_token);

-- updated_at 자동 업데이트를 위한 트리거 함수
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- updated_at 트리거 생성
DROP TRIGGER IF EXISTS update_equipment_updated_at ON equipment;
CREATE TRIGGER update_equipment_updated_at
    BEFORE UPDATE ON equipment
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
