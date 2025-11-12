-- MySQL初期化スクリプト
-- データベース: crypto_pachinko

USE crypto_pachinko;

-- 暗号通貨情報テーブル
CREATE TABLE IF NOT EXISTS cryptocurrencies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL UNIQUE COMMENT '通貨シンボル (BTC, ETH等)',
    name VARCHAR(100) NOT NULL COMMENT '通貨名',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) COMMENT='暗号通貨マスタテーブル';

-- OHLCVデータテーブル（通貨ごと）
CREATE TABLE IF NOT EXISTS ohlcv_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    cryptocurrency_id INT NOT NULL,
    open_price DECIMAL(20, 8) NOT NULL COMMENT 'オープン価格',
    high_price DECIMAL(20, 8) NOT NULL COMMENT '高値',
    low_price DECIMAL(20, 8) NOT NULL COMMENT '安値',
    close_price DECIMAL(20, 8) NOT NULL COMMENT 'クローズ価格',
    volume DECIMAL(20, 8) NOT NULL COMMENT '取引量',
    timestamp_utc TIMESTAMP NOT NULL COMMENT 'データ時刻（UTC）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cryptocurrency_id) REFERENCES cryptocurrencies(id),
    INDEX idx_crypto_timestamp (cryptocurrency_id, timestamp_utc),
    INDEX idx_timestamp_utc (timestamp_utc),
    UNIQUE KEY unique_crypto_timestamp (cryptocurrency_id, timestamp_utc)
) COMMENT='OHLCVデータテーブル';

-- 取引データテーブル
CREATE TABLE IF NOT EXISTS trade_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    cryptocurrency_id INT NOT NULL,
    exchange_name VARCHAR(50) NOT NULL COMMENT 'Exchange name',
    trade_id VARCHAR(100) NOT NULL COMMENT 'Unique trade identifier from the exchange',
    status ENUM('OPEN', 'CANCELLED', 'CLOSED') NOT NULL COMMENT 'Trade status',
    position_type ENUM('LONG', 'SHORT') NOT NULL COMMENT 'Long or Short',
    is_spot BOOLEAN NOT NULL COMMENT 'Is spot trade (TRUE) or margin/futures trade (FALSE)',
    leverage_ratio DECIMAL(5, 2) DEFAULT 1.00 COMMENT 'Leverage ratio (1.00 for spot trades)',
    price DECIMAL(20, 8) NOT NULL COMMENT 'price at which the trade was executed',
    quantity DECIMAL(20, 8) NOT NULL COMMENT 'quantity traded',
    fee DECIMAL(20, 8) NOT NULL COMMENT 'transaction fee (if any / as USDT)',
    timestamp_utc TIMESTAMP NOT NULL COMMENT 'trade execution time (UTC)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cryptocurrency_id) REFERENCES cryptocurrencies(id),
    INDEX idx_crypto_exchange_time (cryptocurrency_id, exchange_name, timestamp_utc),
    INDEX idx_timestamp_utc (timestamp_utc),
    INDEX idx_exchange_name (exchange_name),
    INDEX idx_position_type (position_type),
    INDEX idx_is_spot (is_spot)
) COMMENT='Trade data table';

-- 初期データの投入
INSERT IGNORE INTO cryptocurrencies (symbol, name) VALUES
('BTC', 'Bitcoin'),
('ETH', 'Ethereum'),
('BNB', 'Binance Coin'),
('XRP', 'Ripple'),
('ADA', 'Cardano'),
('SOL', 'Solana'),
('DOGE', 'Dogecoin'),
('DOT', 'Polkadot'),
('MATIC', 'Polygon'),
('AVAX', 'Avalanche');

-- ユーザー権限の確認
SHOW GRANTS FOR 'crypto_user'@'%';
