-- Supabase (PostgreSQL) 용 스키마
CREATE TABLE IF NOT EXISTS equipment (
    id SERIAL PRIMARY KEY,
    model VARCHAR(100) NOT NULL,
    unit_number VARCHAR(100) NOT NULL,
    access_token VARCHAR(64) UNIQUE NOT NULL,
    installation_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_model_unit UNIQUE (model, unit_number)
);

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
