CREATE DATABASE IF NOT EXISTS fnb_insights;
USE fnb_insights;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) UNIQUE NOT NULL,
  password VARCHAR(255) NOT NULL,
  full_name VARCHAR(150) NOT NULL,
  role VARCHAR(30) NOT NULL DEFAULT 'client',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS menu_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  item_name VARCHAR(150) UNIQUE NOT NULL,
  category VARCHAR(80) NOT NULL,
  selling_price DECIMAL(10,2) NOT NULL,
  ingredient_cost DECIMAL(10,2) DEFAULT 0,
  labor_cost DECIMAL(10,2) DEFAULT 0,
  packaging_cost DECIMAL(10,2) DEFAULT 0,
  overhead_cost DECIMAL(10,2) DEFAULT 0,
  quantity_sold INT DEFAULT 0,
  status VARCHAR(20) DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sales (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sale_date DATE NOT NULL,
  menu_item_id INT NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  unit_cost DECIMAL(10,2) NOT NULL,
  extra_expense DECIMAL(10,2) DEFAULT 0,
  channel VARCHAR(50) DEFAULT 'Walk-in',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (menu_item_id) REFERENCES menu_items(id)
);

CREATE TABLE IF NOT EXISTS expenses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  expense_date DATE NOT NULL,
  category VARCHAR(80) NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  note VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS marketing_campaigns (
  id INT AUTO_INCREMENT PRIMARY KEY,
  campaign_date DATE NOT NULL,
  campaign_name VARCHAR(150) NOT NULL,
  platform VARCHAR(80) NOT NULL,
  spend DECIMAL(10,2) NOT NULL,
  revenue_generated DECIMAL(10,2) DEFAULT 0,
  note VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customer_reviews (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_id INT,
  customer_name VARCHAR(150),
  phone_number VARCHAR(30),
  review_date DATE NOT NULL,
  menu_item VARCHAR(150),
  order_type VARCHAR(30),
  source VARCHAR(80) NOT NULL,
  rating INT NOT NULL,
  review_text TEXT NOT NULL,
  receipt_number VARCHAR(80),
  issue_tag VARCHAR(80) DEFAULT 'General',
  urgency_level VARCHAR(20) DEFAULT 'low',
  submission_channel VARCHAR(30) DEFAULT 'manual',
  sentiment_label VARCHAR(20) NOT NULL,
  sentiment_score DECIMAL(8,4) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (client_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS forecast_results (
  id INT AUTO_INCREMENT PRIMARY KEY,
  forecast_date DATE NOT NULL,
  metric VARCHAR(50) NOT NULL,
  value DECIMAL(12,2) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyst_notes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_user_id INT NOT NULL,
  analyst_user_id INT NOT NULL,
  note_text TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (client_user_id) REFERENCES users(id),
  FOREIGN KEY (analyst_user_id) REFERENCES users(id)
);
