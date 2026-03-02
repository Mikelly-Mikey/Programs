#!/usr/bin/env python3
"""
Fresh Fruits Market - Cashier Receipt System
Unified GUI Application for processing customer purchases

REQUIRES MongoDB to be running:
  sudo apt install mongodb
  sudo systemctl start mongodb

Features:
- Cashier inputs products for customer
- Displays price per product
- Calculates total cost
- Processes payments (Cash/Card/M-Pesa)
- Deducts stock from database
- Generates customer receipt
- Product management (add/update/delete)
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import datetime
import uuid
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum

from pymongo import MongoClient


class PaymentMethod(Enum):
    CASH = "cash"
    CARD = "card"
    MPESA = "mpesa"


@dataclass
class Product:
    name: str
    price_per_unit: float
    unit: str
    stock_quantity: float = 0.0
    product_id: Optional[str] = None

    def __post_init__(self):
        if not self.product_id:
            self.product_id = str(uuid.uuid4())[:8].upper()


@dataclass
class CartItem:
    product: Product
    quantity: float

    @property
    def subtotal(self) -> float:
        return self.product.price_per_unit * self.quantity


@dataclass
class PaymentDetails:
    method: PaymentMethod
    amount_paid: float
    transaction_reference: Optional[str] = None
    phone_number: Optional[str] = None
    card_last_four: Optional[str] = None
    card_type: Optional[str] = None
    balance: float = 0.0


@dataclass
class Receipt:
    receipt_number: str
    date: str
    time: str
    items: List[Dict]
    subtotal: float
    tax_amount: float
    total_amount: float
    payment: Dict
    vendor_name: str = "Fresh Fruits Market"
    vendor_address: str = "123 Market Street, Nairobi"
    vendor_phone: str = "+254 700 123 456"


class DatabaseManager:
    """Handles MongoDB operations - MongoDB is required"""
    
    def __init__(self, connection_string: str = "mongodb://localhost:27017/"):
        try:
            self.client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client["fruit_vendor_db"]
            self.products = self.db["products"]
            self.receipts = self.db["receipts"]
        except Exception as e:
            raise ConnectionError(
                f"Cannot connect to MongoDB at {connection_string}\n"
                f"Please ensure MongoDB is installed and running:\n"
                f"  sudo apt install mongodb\n"
                f"  sudo systemctl start mongodb\n"
                f"Original error: {e}"
            )
    
    def add_product(self, product: Product) -> str:
        product_dict = asdict(product)
        self.products.insert_one(product_dict)
        return product.product_id
    
    def get_product(self, product_id: str) -> Optional[Dict]:
        return self.products.find_one({"product_id": product_id})
    
    def get_all_products(self) -> List[Dict]:
        return list(self.products.find())
    
    def update_stock(self, product_id: str, quantity_sold: float) -> bool:
        result = self.products.update_one(
            {"product_id": product_id},
            {"$inc": {"stock_quantity": -quantity_sold}}
        )
        return result.modified_count > 0
    
    def update_product_stock(self, product_id: str, new_stock: float) -> bool:
        """Add/restock product quantity"""
        result = self.products.update_one(
            {"product_id": product_id},
            {"$set": {"stock_quantity": new_stock}}
        )
        return result.modified_count > 0
    
    def update_product_price(self, product_id: str, new_price: float) -> bool:
        """Update product price"""
        result = self.products.update_one(
            {"product_id": product_id},
            {"$set": {"price_per_unit": new_price}}
        )
        return result.modified_count > 0
    
    def delete_product(self, product_id: str) -> bool:
        """Remove product from database"""
        result = self.products.delete_one({"product_id": product_id})
        return result.deleted_count > 0
    
    def save_transaction(self, receipt: Receipt) -> str:
        receipt_dict = asdict(receipt)
        receipt_dict["created_at"] = datetime.datetime.now()
        result = self.receipts.insert_one(receipt_dict)
        return str(result.inserted_id)


class PaymentProcessor:
    TAX_RATE = 0.16
    VAT_INCLUSIVE = True  # Set to True for VAT-inclusive pricing
    
    @staticmethod
    def calculate_totals(items: List[CartItem]) -> tuple:
        """Calculate totals with VAT-inclusive pricing"""
        # Subtotal = sum of all item subtotals (prices include VAT)
        subtotal = sum(item.subtotal for item in items)
        
        if PaymentProcessor.VAT_INCLUSIVE:
            # VAT is already included in subtotal
            # Calculate VAT component: subtotal - (subtotal / 1.16)
            tax_amount = subtotal - (subtotal / 1.16)
            total = subtotal  # Total equals subtotal (VAT inclusive)
        else:
            # VAT is added on top
            tax_amount = subtotal * PaymentProcessor.TAX_RATE
            total = subtotal + tax_amount
        
        return subtotal, tax_amount, total
    
    def process_cash_payment(self, total: float, amount_tendered: float) -> PaymentDetails:
        if amount_tendered < total:
            raise ValueError("Insufficient amount tendered")
        balance = amount_tendered - total
        return PaymentDetails(method=PaymentMethod.CASH, amount_paid=amount_tendered, balance=balance)
    
    def process_card_payment(self, total: float, card_number: str, card_type: str, auth_code: str) -> PaymentDetails:
        last_four = card_number[-4:] if len(card_number) >= 4 else "****"
        return PaymentDetails(method=PaymentMethod.CARD, amount_paid=total,
                              transaction_reference=auth_code, card_last_four=last_four,
                              card_type=card_type, balance=0.0)
    
    def process_mpesa_payment(self, total: float, phone_number: str, mpesa_code: str) -> PaymentDetails:
        return PaymentDetails(method=PaymentMethod.MPESA, amount_paid=total,
                              phone_number=phone_number, transaction_reference=mpesa_code, balance=0.0)


class MarketReceiptApp:
    def __init__(self, db_connection: str = "mongodb://localhost:27017/"):
        self.db = DatabaseManager(db_connection)
        self.payment_processor = PaymentProcessor()
        self.cart: List[CartItem] = []
        self._initialize_sample_products()
    
    def _initialize_sample_products(self):
        if not self.db.get_all_products():
            sample_products = [
                Product("Apples", 50.0, "piece", 100.0),
                Product("Ripe Banana", 10.0, "piece", 150.0),
                Product("Oranges", 10.0, "piece", 80.0),
                Product("Mangoes", 50.0, "piece", 200.0),
                Product("Pineapples", 80.0, "piece", 50.0),
                Product("Watermelon", 300.0, "piece", 30.0),
                Product("Coconut", 120.0, "piece", 30.0),
                Product("Grapes", 400.0, "punnet", 40.0),
                Product("Strawberries", 500.0, "punnet", 60.0),
            ]
            for product in sample_products:
                self.db.add_product(product)
    
    def get_all_products(self) -> List[Dict]:
        return self.db.get_all_products()
    
    def add_to_cart(self, product_id: str, quantity: float) -> tuple[bool, str]:
        product_data = self.db.get_product(product_id)
        if not product_data:
            return False, "Product not found!"
        if product_data['stock_quantity'] < quantity:
            return False, f"Insufficient stock! Available: {product_data['stock_quantity']:.1f}"
        product = Product(name=product_data['name'], price_per_unit=product_data['price_per_unit'],
                          unit=product_data['unit'], stock_quantity=product_data['stock_quantity'],
                          product_id=product_data['product_id'])
        self.cart.append(CartItem(product, quantity))
        return True, f"Added {quantity} {product.unit} of {product.name}"
    
    def remove_from_cart(self, index: int):
        if 0 <= index < len(self.cart):
            self.cart.pop(index)
    
    def clear_cart(self):
        self.cart = []
    
    def get_cart_items(self) -> List[CartItem]:
        return self.cart
    
    def update_product_stock(self, product_id: str, new_stock: float) -> tuple[bool, str]:
        """Add or restock product"""
        product_data = self.db.get_product(product_id)
        if not product_data:
            return False, "Product not found!"
        if self.db.update_product_stock(product_id, new_stock):
            return True, f"Stock updated for {product_data['name']} to {new_stock:.1f}"
        return False, "Failed to update stock"
    
    def update_product_price(self, product_id: str, new_price: float) -> tuple[bool, str]:
        """Update product price"""
        product_data = self.db.get_product(product_id)
        if not product_data:
            return False, "Product not found!"
        if new_price <= 0:
            return False, "Price must be greater than 0"
        if self.db.update_product_price(product_id, new_price):
            return True, f"Price updated for {product_data['name']} to KES {new_price:.2f}"
        return False, "Failed to update price"
    
    def add_new_product(self, name: str, price: float, unit: str, stock: float) -> tuple[bool, str]:
        """Add a new product to database"""
        if price <= 0:
            return False, "Price must be greater than 0"
        if stock < 0:
            return False, "Stock cannot be negative"
        product = Product(name=name, price_per_unit=price, unit=unit, stock_quantity=stock)
        self.db.add_product(product)
        return True, f"Product '{name}' added with ID: {product.product_id}"
    
    def delete_product(self, product_id: str) -> tuple[bool, str]:
        """Remove product from database"""
        product_data = self.db.get_product(product_id)
        if not product_data:
            return False, "Product not found!"
        if self.db.delete_product(product_id):
            return True, f"Product '{product_data['name']}' deleted"
        return False, "Failed to delete product"
    
    def calculate_totals(self) -> tuple:
        return self.payment_processor.calculate_totals(self.cart)
    
    def checkout(self, payment_method: PaymentMethod, **kwargs) -> Optional[Receipt]:
        if not self.cart:
            return None
        
        subtotal, tax_amount, total = self.payment_processor.calculate_totals(self.cart)
        
        try:
            if payment_method == PaymentMethod.CASH:
                amount_tendered = kwargs.get('amount_tendered', 0)
                payment_details = self.payment_processor.process_cash_payment(total, amount_tendered)
            elif payment_method == PaymentMethod.CARD:
                card_number = kwargs.get('card_number', '')
                card_type = kwargs.get('card_type', 'Card')
                auth_code = kwargs.get('auth_code', str(uuid.uuid4())[:6].upper())
                payment_details = self.payment_processor.process_card_payment(total, card_number, card_type, auth_code)
            elif payment_method == PaymentMethod.MPESA:
                phone_number = kwargs.get('phone_number', '')
                mpesa_code = kwargs.get('mpesa_code', '' + str(uuid.uuid4())[:6].upper())
                payment_details = self.payment_processor.process_mpesa_payment(total, phone_number, mpesa_code)
            else:
                return None
        except ValueError:
            return None
        
        now = datetime.datetime.now()
        items_data = [{"product_name": item.product.name, "quantity": item.quantity,
                       "unit": item.product.unit, "unit_price": item.product.price_per_unit,
                       "subtotal": item.subtotal} for item in self.cart]
        
        receipt = Receipt(
            receipt_number=f"RCP-{uuid.uuid4().hex[:8].upper()}",
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            items=items_data,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total_amount=total,
            payment={
                "method": payment_details.method.value,
                "amount_paid": payment_details.amount_paid,
                "balance": payment_details.balance,
                "transaction_reference": payment_details.transaction_reference,
                "phone_number": payment_details.phone_number,
                "card_last_four": payment_details.card_last_four,
                "card_type": payment_details.card_type
            }
        )
        
        # Deduct stock from database
        for item in self.cart:
            self.db.update_stock(item.product.product_id, item.quantity)
        
        self.db.save_transaction(receipt)
        self.cart = []
        
        return receipt
    
    def format_receipt(self, receipt: Receipt) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("           FRESH FRUITS MARKET")
        lines.append("        " + receipt.vendor_address)
        lines.append("          Tel: " + receipt.vendor_phone)
        lines.append("=" * 60)
        lines.append(f"Receipt No: {receipt.receipt_number}")
        lines.append(f"Date: {receipt.date}          Time: {receipt.time}")
        lines.append("-" * 60)
        lines.append(f"{'Item':<18}{'Qty':<10}{'Price':<12}{'Total':<12}")
        lines.append("-" * 60)
        
        for item in receipt.items:
            qty_str = f"{item['quantity']:.1f} {item['unit']}"
            lines.append(f"{item['product_name']:<18}{qty_str:<10}{item['unit_price']:<12.2f}{item['subtotal']:<12.2f}")
        
        lines.append("-" * 60)
        
        # VAT-inclusive display
        if abs(receipt.subtotal - receipt.total_amount) < 0.01:  # VAT inclusive
            lines.append(f"{'Subtotal (incl. VAT):':<40}{receipt.subtotal:>18.2f}")
            lines.append(f"{'VAT Included (16%):':<40}{receipt.tax_amount:>18.2f}")
            lines.append(f"{'TOTAL:':<40}{receipt.total_amount:>18.2f}")
        else:  # VAT exclusive
            lines.append(f"{'Subtotal:':<40}{receipt.subtotal:>18.2f}")
            lines.append(f"{'VAT (16%):':<40}{receipt.tax_amount:>18.2f}")
            lines.append(f"{'TOTAL:':<40}{receipt.total_amount:>18.2f}")
        
        lines.append("-" * 60)
        
        payment = receipt.payment
        lines.append(f"Payment: {payment['method'].upper()}")
        lines.append(f"Amount Paid: {payment['amount_paid']:>.2f}")
        
        if payment['balance'] > 0:
            lines.append(f"BALANCE: {payment['balance']:.2f}")
        
        if payment.get('transaction_reference'):
            lines.append(f"Ref: {payment['transaction_reference']}")
        
        if payment.get('phone_number'):
            lines.append(f"M-Pesa: {payment['phone_number']}")
        
        if payment.get('card_last_four'):
            card_type = payment.get('card_type', 'Card')
            lines.append(f"{card_type}: ****{payment['card_last_four']}")
        
        lines.append("=" * 60)
        lines.append("     Thank you for shopping with us!")
        lines.append("        Please come again!")
        lines.append("=" * 60)
        
        return "\n".join(lines)


class CashierReceiptSystemGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Fresh Fruits Market - Cashier System")
        self.root.geometry("1000x800")
        
        try:
            self.app = MarketReceiptApp()
        except ConnectionError as e:
            messagebox.showerror("Database Error", str(e))
            self.root.destroy()
            return
        
        self.setup_ui()
        self.refresh_products()
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(header_frame, text="FRESH FRUITS MARKET", font=('Arial', 20, 'bold')).pack()
        ttk.Label(header_frame, text="Cashier Receipt System", font=('Arial', 12)).pack()
        
        # Product Management Button
        ttk.Button(header_frame, text="Manage Products", 
                  command=self.open_product_manager).pack(pady=(5, 0))
        
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=1)
        
        left_frame = ttk.LabelFrame(content_frame, text="Available Products", padding="10")
        left_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        
        prod_container = ttk.Frame(left_frame)
        prod_container.pack(fill=tk.BOTH, expand=True)
        
        self.product_tree = ttk.Treeview(prod_container, 
                                         columns=('ID', 'Name', 'Price', 'Unit', 'Stock'), 
                                         show='headings', height=12)
        self.product_tree.heading('ID', text='ID')
        self.product_tree.heading('Name', text='Product Name')
        self.product_tree.heading('Price', text='Price (KES)')
        self.product_tree.heading('Unit', text='Unit')
        self.product_tree.heading('Stock', text='In Stock')
        self.product_tree.column('ID', width=70)
        self.product_tree.column('Name', width=140)
        self.product_tree.column('Price', width=90, anchor=tk.E)
        self.product_tree.column('Unit', width=70)
        self.product_tree.column('Stock', width=70, anchor=tk.E)
        
        prod_scroll = ttk.Scrollbar(prod_container, orient=tk.VERTICAL, command=self.product_tree.yview)
        self.product_tree.configure(yscrollcommand=prod_scroll.set)
        self.product_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        prod_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        add_frame = ttk.Frame(left_frame)
        add_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(add_frame, text="Quantity:", font=('Arial', 11)).pack(side=tk.LEFT)
        self.quantity_var = tk.StringVar(value="1")
        qty_entry = ttk.Entry(add_frame, textvariable=self.quantity_var, width=10, font=('Arial', 11))
        qty_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(add_frame, text="ADD TO CART", command=self.add_to_cart).pack(side=tk.LEFT, padx=10)
        
        right_frame = ttk.Frame(content_frame)
        right_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        
        cart_frame = ttk.LabelFrame(right_frame, text="Customer's Cart", padding="10")
        cart_frame.pack(fill=tk.BOTH, expand=True)
        
        cart_container = ttk.Frame(cart_frame)
        cart_container.pack(fill=tk.BOTH, expand=True)
        
        self.cart_tree = ttk.Treeview(cart_container, 
                                     columns=('Product', 'Qty', 'Unit', 'Price', 'Subtotal'), 
                                     show='headings', height=8)
        self.cart_tree.heading('Product', text='Product')
        self.cart_tree.heading('Qty', text='Qty')
        self.cart_tree.heading('Unit', text='Unit')
        self.cart_tree.heading('Price', text='Unit Price')
        self.cart_tree.heading('Subtotal', text='Amount')
        self.cart_tree.column('Product', width=120)
        self.cart_tree.column('Qty', width=60, anchor=tk.E)
        self.cart_tree.column('Unit', width=60)
        self.cart_tree.column('Price', width=80, anchor=tk.E)
        self.cart_tree.column('Subtotal', width=80, anchor=tk.E)
        
        cart_scroll = ttk.Scrollbar(cart_container, orient=tk.VERTICAL, command=self.cart_tree.yview)
        self.cart_tree.configure(yscrollcommand=cart_scroll.set)
        self.cart_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cart_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        cart_btn_frame = ttk.Frame(cart_frame)
        cart_btn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(cart_btn_frame, text="Remove Selected", command=self.remove_from_cart).pack(side=tk.LEFT, padx=5)
        ttk.Button(cart_btn_frame, text="Clear All", command=self.clear_cart).pack(side=tk.LEFT, padx=5)
        
        totals_frame = ttk.Frame(cart_frame)
        totals_frame.pack(fill=tk.X, pady=(15, 0))
        
        self.subtotal_var = tk.StringVar(value="Subtotal: KES 0.00")
        self.tax_var = tk.StringVar(value="VAT (16%): KES 0.00")
        self.total_var = tk.StringVar(value="TOTAL: KES 0.00")
        
        ttk.Label(totals_frame, textvariable=self.subtotal_var, font=('Arial', 11)).pack(anchor=tk.E)
        ttk.Label(totals_frame, textvariable=self.tax_var, font=('Arial', 11)).pack(anchor=tk.E)
        ttk.Separator(totals_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)
        ttk.Label(totals_frame, textvariable=self.total_var, font=('Arial', 14, 'bold'), foreground='green').pack(anchor=tk.E)
        
        payment_frame = ttk.LabelFrame(right_frame, text="Payment Method", padding="10")
        payment_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.payment_method = tk.StringVar(value="cash")
        pm_frame = ttk.Frame(payment_frame)
        pm_frame.pack(fill=tk.X)
        ttk.Radiobutton(pm_frame, text="Cash", variable=self.payment_method, 
                       value="cash", command=self.update_payment_fields).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(pm_frame, text="Card", variable=self.payment_method, 
                       value="card", command=self.update_payment_fields).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(pm_frame, text="M-Pesa", variable=self.payment_method, 
                       value="mpesa", command=self.update_payment_fields).pack(side=tk.LEFT, padx=10)
        
        self.payment_details_frame = ttk.Frame(payment_frame)
        self.payment_details_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.cash_frame = ttk.Frame(self.payment_details_frame)
        ttk.Label(self.cash_frame, text="Amount Tendered (KES):").pack(side=tk.LEFT)
        self.cash_amount = ttk.Entry(self.cash_frame, width=15, font=('Arial', 11))
        self.cash_amount.pack(side=tk.LEFT, padx=5)
        
        self.card_frame = ttk.Frame(self.payment_details_frame)
        ttk.Label(self.card_frame, text="Card Type:").pack(side=tk.LEFT)
        self.card_type = ttk.Combobox(self.card_frame, values=["Mastercard", "Visa", "ATM Card"], 
                                      width=12, state="readonly")
        self.card_type.set("Visa")
        self.card_type.pack(side=tk.LEFT, padx=5)
        ttk.Label(self.card_frame, text="Card #:").pack(side=tk.LEFT)
        self.card_number = ttk.Entry(self.card_frame, width=20, font=('Arial', 11))
        self.card_number.pack(side=tk.LEFT, padx=5)
        
        self.mpesa_frame = ttk.Frame(self.payment_details_frame)
        ttk.Label(self.mpesa_frame, text="Phone:").pack(side=tk.LEFT)
        self.mpesa_phone = ttk.Entry(self.mpesa_frame, width=15, font=('Arial', 11))
        self.mpesa_phone.pack(side=tk.LEFT, padx=5)
        ttk.Label(self.mpesa_frame, text="M-Pesa Code:").pack(side=tk.LEFT)
        self.mpesa_code = ttk.Entry(self.mpesa_frame, width=15, font=('Arial', 11))
        self.mpesa_code.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(payment_frame, text="PROCESS PAYMENT & PRINT RECEIPT", 
                  command=self.checkout).pack(fill=tk.X, pady=(15, 0))
        
        receipt_frame = ttk.LabelFrame(main_frame, text="Customer Receipt (Give This to Customer)", padding="10")
        receipt_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        self.receipt_text = scrolledtext.ScrolledText(receipt_frame, wrap=tk.WORD,
                                                      font=('Courier', 11), bg='white')
        self.receipt_text.pack(fill=tk.BOTH, expand=True)
        
        ttk.Button(receipt_frame, text="Print Receipt", command=self.print_receipt).pack(side=tk.LEFT, padx=5)
        ttk.Button(receipt_frame, text="View Full Receipt", command=self.show_full_receipt).pack(side=tk.LEFT, padx=5)
        
        self.update_payment_fields()
    
    def open_product_manager(self):
        """Open product management dialog"""
        manager_window = tk.Toplevel(self.root)
        manager_window.title("Product Management")
        manager_window.geometry("500x600")
        
        # Frame for adding new product
        add_frame = ttk.LabelFrame(manager_window, text="Add New Product", padding="10")
        add_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(add_frame, text="Name:").grid(row=0, column=0, sticky=tk.W)
        self.new_name = ttk.Entry(add_frame, width=20)
        self.new_name.grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(add_frame, text="Price (KES):").grid(row=1, column=0, sticky=tk.W)
        self.new_price = ttk.Entry(add_frame, width=20)
        self.new_price.grid(row=1, column=1, padx=5, pady=2)
        
        ttk.Label(add_frame, text="Unit:").grid(row=2, column=0, sticky=tk.W)
        self.new_unit = ttk.Combobox(add_frame, values=["kg", "piece", "bunch", "punnet", "box"], width=18)
        self.new_unit.set("kg")
        self.new_unit.grid(row=2, column=1, padx=5, pady=2)
        
        ttk.Label(add_frame, text="Stock:").grid(row=3, column=0, sticky=tk.W)
        self.new_stock = ttk.Entry(add_frame, width=20)
        self.new_stock.insert(0, "0")
        self.new_stock.grid(row=3, column=1, padx=5, pady=2)
        
        ttk.Button(add_frame, text="Add Product", command=self.add_new_product_gui).grid(row=4, column=0, columnspan=2, pady=10)
        
        # Frame for updating existing product
        update_frame = ttk.LabelFrame(manager_window, text="Update Existing Product", padding="10")
        update_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(update_frame, text="Select Product:").grid(row=0, column=0, sticky=tk.W)
        products = self.app.get_all_products()
        product_list = [f"{p['product_id']} - {p['name']}" for p in products]
        self.selected_product = ttk.Combobox(update_frame, values=product_list, width=30)
        self.selected_product.grid(row=0, column=1, padx=5, pady=2)
        self.selected_product.bind('<<ComboboxSelected>>', self.on_product_select)
        
        self.current_info = ttk.Label(update_frame, text="Current: Stock: - | Price: KES -")
        self.current_info.grid(row=1, column=0, columnspan=2, pady=5)
        
        ttk.Label(update_frame, text="New Stock:").grid(row=2, column=0, sticky=tk.W)
        self.update_stock_val = ttk.Entry(update_frame, width=20)
        self.update_stock_val.grid(row=2, column=1, padx=5, pady=2)
        ttk.Button(update_frame, text="Update Stock", command=self.update_stock_gui).grid(row=3, column=0, columnspan=2, pady=5)
        
        ttk.Label(update_frame, text="New Price (KES):").grid(row=4, column=0, sticky=tk.W)
        self.update_price_val = ttk.Entry(update_frame, width=20)
        self.update_price_val.grid(row=4, column=1, padx=5, pady=2)
        ttk.Button(update_frame, text="Update Price", command=self.update_price_gui).grid(row=5, column=0, columnspan=2, pady=5)
        
        ttk.Separator(update_frame, orient=tk.HORIZONTAL).grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=10)
        ttk.Button(update_frame, text="Delete Selected Product", 
                  command=self.delete_product_gui, foreground='red').grid(row=7, column=0, columnspan=2, pady=5)
        
        ttk.Button(manager_window, text="Close", command=manager_window.destroy).pack(pady=10)
    
    def on_product_select(self, event=None):
        selected = self.selected_product.get()
        if selected:
            product_id = selected.split(" - ")[0]
            product_data = self.app.db.get_product(product_id)
            if product_data:
                self.current_info.config(
                    text=f"Current: Stock: {product_data['stock_quantity']:.1f} | Price: KES {product_data['price_per_unit']:.2f}"
                )
    
    def add_new_product_gui(self):
        try:
            name = self.new_name.get().strip()
            price = float(self.new_price.get())
            unit = self.new_unit.get()
            stock = float(self.new_stock.get())
            
            if not name:
                messagebox.showerror("Error", "Product name is required")
                return
            
            success, message = self.app.add_new_product(name, price, unit, stock)
            if success:
                messagebox.showinfo("Success", message)
                self.new_name.delete(0, tk.END)
                self.new_price.delete(0, tk.END)
                self.new_stock.delete(0, tk.END)
                self.new_stock.insert(0, "0")
                self.refresh_products()
                products = self.app.get_all_products()
                self.selected_product['values'] = [f"{p['product_id']} - {p['name']}" for p in products]
            else:
                messagebox.showerror("Error", message)
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers for price and stock")
    
    def update_stock_gui(self):
        try:
            selected = self.selected_product.get()
            if not selected:
                messagebox.showerror("Error", "Please select a product")
                return
            product_id = selected.split(" - ")[0]
            new_stock = float(self.update_stock_val.get())
            
            success, message = self.app.update_product_stock(product_id, new_stock)
            if success:
                messagebox.showinfo("Success", message)
                self.update_stock_val.delete(0, tk.END)
                self.refresh_products()
                self.on_product_select()
            else:
                messagebox.showerror("Error", message)
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid stock quantity")
    
    def update_price_gui(self):
        try:
            selected = self.selected_product.get()
            if not selected:
                messagebox.showerror("Error", "Please select a product")
                return
            product_id = selected.split(" - ")[0]
            new_price = float(self.update_price_val.get())
            
            success, message = self.app.update_product_price(product_id, new_price)
            if success:
                messagebox.showinfo("Success", message)
                self.update_price_val.delete(0, tk.END)
                self.refresh_products()
                self.on_product_select()
            else:
                messagebox.showerror("Error", message)
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid price")
    
    def delete_product_gui(self):
        selected = self.selected_product.get()
        if not selected:
            messagebox.showerror("Error", "Please select a product")
            return
        
        product_id = selected.split(" - ")[0]
        product_name = selected.split(" - ")[1]
        
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{product_name}'?"):
            success, message = self.app.delete_product(product_id)
            if success:
                messagebox.showinfo("Success", message)
                self.selected_product.set('')
                self.refresh_products()
                products = self.app.get_all_products()
                self.selected_product['values'] = [f"{p['product_id']} - {p['name']}" for p in products]
                self.current_info.config(text="Current: Stock: - | Price: KES -")
            else:
                messagebox.showerror("Error", message)
    
    def update_payment_fields(self):
        self.cash_frame.pack_forget()
        self.card_frame.pack_forget()
        self.mpesa_frame.pack_forget()
        method = self.payment_method.get()
        if method == "cash":
            self.cash_frame.pack(fill=tk.X)
        elif method == "card":
            self.card_frame.pack(fill=tk.X)
        elif method == "mpesa":
            self.mpesa_frame.pack(fill=tk.X)
    
    def refresh_products(self):
        for item in self.product_tree.get_children():
            self.product_tree.delete(item)
        products = self.app.get_all_products()
        for p in products:
            self.product_tree.insert('', tk.END, values=(
                p['product_id'], p['name'], f"{p['price_per_unit']:.2f}", 
                p['unit'], f"{p['stock_quantity']:.1f}"
            ))
    
    def refresh_cart(self):
        for item in self.cart_tree.get_children():
            self.cart_tree.delete(item)
        cart_items = self.app.get_cart_items()
        for item in cart_items:
            self.cart_tree.insert('', tk.END, values=(
                item.product.name, f"{item.quantity:.1f}", item.product.unit,
                f"{item.product.price_per_unit:.2f}", f"{item.subtotal:.2f}"
            ))
        if cart_items:
            subtotal, tax, total = self.app.calculate_totals()
            self.subtotal_var.set(f"Subtotal: KES {subtotal:.2f}")
            self.tax_var.set(f"VAT (16%): KES {tax:.2f}")
            self.total_var.set(f"TOTAL: KES {total:.2f}")
        else:
            self.subtotal_var.set("Subtotal: KES 0.00")
            self.tax_var.set("VAT (16%): KES 0.00")
            self.total_var.set("TOTAL: KES 0.00")
    
    def add_to_cart(self):
        selected = self.product_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a product first")
            return
        try:
            quantity = float(self.quantity_var.get())
            if quantity <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid Quantity", "Please enter a valid positive number")
            return
        item = self.product_tree.item(selected[0])
        product_id = item['values'][0]
        success, message = self.app.add_to_cart(product_id, quantity)
        if success:
            self.refresh_cart()
            messagebox.showinfo("Success", message)
        else:
            messagebox.showerror("Error", message)
    
    def remove_from_cart(self):
        selected = self.cart_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select an item to remove")
            return
        index = self.cart_tree.index(selected[0])
        self.app.remove_from_cart(index)
        self.refresh_cart()
    
    def clear_cart(self):
        self.app.clear_cart()
        self.refresh_cart()
    
    def show_full_receipt(self):
        """Display receipt in a large window for full visibility"""
        receipt_content = self.receipt_text.get(1.0, tk.END).strip()
        if not receipt_content:
            messagebox.showwarning("No Receipt", "Generate a receipt first!")
            return
        
        # Create large popup window
        full_window = tk.Toplevel(self.root)
        full_window.title("FULL RECEIPT - Customer Copy")
        full_window.geometry("700x750")
        full_window.configure(bg='white')
        
        # Make window modal
        full_window.transient(self.root)
        full_window.grab_set()
        
        # Header
        header = ttk.Label(full_window, text="CUSTOMER RECEIPT", 
                          font=('Arial', 16, 'bold'))
        header.pack(pady=(10, 5))
        
        # Receipt display - no scroll, full height
        receipt_display = tk.Text(full_window, wrap=tk.WORD,
                                  font=('Courier', 12), bg='white',
                                  padx=20, pady=20, height=35, width=60)
        receipt_display.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        receipt_display.insert(1.0, receipt_content)
        receipt_display.config(state=tk.DISABLED)
        
        # Button frame
        btn_frame = ttk.Frame(full_window)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="Print", command=lambda: self.print_from_full(receipt_content)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Close", command=full_window.destroy).pack(side=tk.LEFT, padx=5)
        
        # Auto-show after checkout
        self.root.update_idletasks()
    
    def print_from_full(self, content):
        """Print from full receipt view"""
        messagebox.showinfo("Print", "Receipt sent to printer!")
    
    def checkout(self):
        cart_items = self.app.get_cart_items()
        if not cart_items:
            messagebox.showwarning("Empty Cart", "Cart is empty! Add items first.")
            return
        method = self.payment_method.get()
        payment_details = {}
        if method == "cash":
            try:
                amount = float(self.cash_amount.get())
                payment_details = {"amount_tendered": amount}
            except ValueError:
                messagebox.showerror("Invalid Amount", "Please enter a valid amount")
                return
        elif method == "card":
            card_num = self.card_number.get().strip()
            if not card_num:
                messagebox.showerror("Invalid Card", "Please enter card number")
                return
            payment_details = {"card_number": card_num, "card_type": self.card_type.get()}
        elif method == "mpesa":
            phone = self.mpesa_phone.get().strip()
            code = self.mpesa_code.get().strip()
            if not phone:
                messagebox.showerror("Invalid Phone", "Please enter phone number")
                return
            payment_details = {"phone_number": phone, "mpesa_code": code}
        pm = PaymentMethod(method)
        receipt = self.app.checkout(pm, **payment_details)
        if receipt:
            receipt_text = self.app.format_receipt(receipt)
            self.receipt_text.delete(1.0, tk.END)
            self.receipt_text.insert(1.0, receipt_text)
            self.refresh_cart()
            self.refresh_products()
            # Auto-show full receipt
            self.show_full_receipt()
        else:
            messagebox.showerror("Error", "Checkout failed. Please check payment details.")
    
    def print_receipt(self):
        receipt_content = self.receipt_text.get(1.0, tk.END).strip()
        if not receipt_content:
            messagebox.showwarning("No Receipt", "No receipt to print!")
            return
        print_window = tk.Toplevel(self.root)
        print_window.title("Print Receipt")
        print_window.geometry("400x300")
        ttk.Label(print_window, text="Receipt ready to print", font=('Arial', 12, 'bold')).pack(pady=10)
        text_area = scrolledtext.ScrolledText(print_window, wrap=tk.WORD, font=('Courier', 10))
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_area.insert(1.0, receipt_content)
        text_area.config(state=tk.DISABLED)
        ttk.Button(print_window, text="Close", command=print_window.destroy).pack(pady=10)
        messagebox.showinfo("Print", "Receipt sent to printer!", parent=print_window)


def main():
    root = tk.Tk()
    app = CashierReceiptSystemGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
