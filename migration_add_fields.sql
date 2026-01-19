-- Migration: Add export_country, qr_registered_date, shipment_date, and order_number fields to equipment table
-- Execute this in your Supabase SQL editor to add the new fields to your existing database

-- Add order_number column
ALTER TABLE equipment ADD COLUMN IF NOT EXISTS order_number VARCHAR(100);

-- Add export_country column
ALTER TABLE equipment ADD COLUMN IF NOT EXISTS export_country VARCHAR(100);

-- Add qr_registered_date column
ALTER TABLE equipment ADD COLUMN IF NOT EXISTS qr_registered_date DATE;

-- Add shipment_date column
ALTER TABLE equipment ADD COLUMN IF NOT EXISTS shipment_date DATE;

-- Optional: Update existing records to set qr_registered_date to created_at date
-- This will maintain consistency with the new behavior
UPDATE equipment
SET qr_registered_date = DATE(created_at)
WHERE qr_registered_date IS NULL;

-- =====================================================
-- Migration Part 2: Add carrier_info and dealer_code fields
-- Execute this in your Supabase SQL editor
-- =====================================================

-- Add carrier_info column (vehicle/carrier information)
ALTER TABLE equipment ADD COLUMN IF NOT EXISTS carrier_info VARCHAR(200);

-- Add dealer_code column (dealer identification code)
ALTER TABLE equipment ADD COLUMN IF NOT EXISTS dealer_code VARCHAR(100);

-- Add comments for documentation
COMMENT ON COLUMN equipment.carrier_info IS 'Vehicle/carrier information for the equipment';
COMMENT ON COLUMN equipment.dealer_code IS 'Dealer identification code';
