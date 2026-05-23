CREATE DATABASE IF NOT EXISTS fnb_insights;
USE fnb_insights;

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS analyst_notes;
DROP TABLE IF EXISTS forecast_results;
DROP TABLE IF EXISTS stock_movements;
DROP TABLE IF EXISTS inventory_items;
DROP TABLE IF EXISTS customer_reviews;
DROP TABLE IF EXISTS marketing_campaigns;
DROP TABLE IF EXISTS expenses;
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS menu_items;
DROP TABLE IF EXISTS users;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) UNIQUE NOT NULL,
  password VARCHAR(255) NOT NULL,
  full_name VARCHAR(150) NOT NULL,
  role VARCHAR(30) NOT NULL DEFAULT 'client',
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  last_login_at DATETIME NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO users (username, password, full_name, role, status) VALUES
  (
    'admin',
    'pbkdf2:sha256:600000$serveiq_admin_demo$0f23b17c41ee14aa5bb226e433cda8e4c8bb4dd864b6aac270f3d2b20ca391e1',
    'SME Consultant',
    'admin_analyst',
    'active'
  ),
  (
    'client',
    'pbkdf2:sha256:600000$serveiq_client_demo$cc459b4b7d0797622d5a16bc1113239c636c88ade4920d0fd45f2721afda20a2',
    'SME Client',
    'client',
    'active'
  );

CREATE TABLE menu_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_id INT NOT NULL,
  item_name VARCHAR(150) NOT NULL,
  category VARCHAR(80) NOT NULL,
  selling_price DECIMAL(10,2) NOT NULL,
  ingredient_cost DECIMAL(10,2) DEFAULT 0,
  labor_cost DECIMAL(10,2) DEFAULT 0,
  packaging_cost DECIMAL(10,2) DEFAULT 0,
  overhead_cost DECIMAL(10,2) DEFAULT 0,
  status VARCHAR(20) DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  CONSTRAINT fk_menu_items_client
    FOREIGN KEY (client_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,

  UNIQUE KEY uq_menu_client_item (client_id, item_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sales (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_id INT NOT NULL,
  sale_date DATE NOT NULL,
  menu_item_id INT NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  unit_cost DECIMAL(10,2) NOT NULL,
  extra_expense DECIMAL(10,2) DEFAULT 0,
  channel VARCHAR(50) DEFAULT 'Walk-in',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_sales_client
    FOREIGN KEY (client_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,

  CONSTRAINT fk_sales_menu_item
    FOREIGN KEY (menu_item_id) REFERENCES menu_items(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE expenses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_id INT NOT NULL,
  expense_date DATE NOT NULL,
  category VARCHAR(80) NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  note VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_expenses_client
    FOREIGN KEY (client_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE marketing_campaigns (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_id INT NOT NULL,
  campaign_date DATE NOT NULL,
  campaign_name VARCHAR(150) NOT NULL,
  platform VARCHAR(80) NOT NULL,
  spend DECIMAL(10,2) NOT NULL,
  revenue_generated DECIMAL(10,2) DEFAULT 0,
  note VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_marketing_campaigns_client
    FOREIGN KEY (client_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE customer_reviews (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_id INT NOT NULL,
  customer_name VARCHAR(150),
  phone_number VARCHAR(30),
  review_date DATE NOT NULL,
  menu_item VARCHAR(150),
  order_type VARCHAR(50) DEFAULT 'Dine-in',
  source VARCHAR(80) NOT NULL DEFAULT 'QR Form',
  rating INT NOT NULL,
  review_text TEXT NOT NULL,
  receipt_number VARCHAR(80),
  issue_tag VARCHAR(80) DEFAULT 'General',
  urgency_level VARCHAR(30) DEFAULT 'Normal',
  submission_channel VARCHAR(50) DEFAULT 'QR Form',
  sentiment_label VARCHAR(20) NOT NULL DEFAULT 'Neutral',
  sentiment_score DECIMAL(8,4) NOT NULL DEFAULT 0.0000,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  CONSTRAINT fk_customer_reviews_client
    FOREIGN KEY (client_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE forecast_results (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_id INT NOT NULL,
  forecast_date DATE NOT NULL,
  metric VARCHAR(50) NOT NULL,
  value DECIMAL(12,2) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_forecast_results_client
    FOREIGN KEY (client_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE inventory_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_id INT NOT NULL,
  ingredient_name VARCHAR(150) NOT NULL,
  category VARCHAR(80) NOT NULL,
  unit VARCHAR(30) NOT NULL,
  current_stock DECIMAL(12,2) NOT NULL DEFAULT 0,
  minimum_stock DECIMAL(12,2) NOT NULL DEFAULT 0,
  cost_per_unit DECIMAL(10,2) NOT NULL DEFAULT 0,
  supplier_name VARCHAR(150),
  last_restock_date DATE,
  status VARCHAR(20) DEFAULT 'active',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  CONSTRAINT fk_inventory_items_client
    FOREIGN KEY (client_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE stock_movements (
  id INT AUTO_INCREMENT PRIMARY KEY,
  inventory_item_id INT NOT NULL,
  movement_type VARCHAR(20) NOT NULL,
  quantity DECIMAL(12,2) NOT NULL,
  movement_date DATE NOT NULL,
  note VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_stock_movements_inventory_item
    FOREIGN KEY (inventory_item_id) REFERENCES inventory_items(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE analyst_notes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  client_user_id INT NOT NULL,
  analyst_user_id INT NOT NULL,
  note_text TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_analyst_notes_client
    FOREIGN KEY (client_user_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE,

  CONSTRAINT fk_analyst_notes_analyst
    FOREIGN KEY (analyst_user_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
