// backend/src/models/Product.js
// Mongoose schema and model for Product

const mongoose = require('mongoose');

const productSchema = new mongoose.Schema(
  {
    name: {
      type: String,
      required: [true, 'Product name is required'],
      trim: true,
      minlength: [1, 'Product name cannot be empty'],
    },
    price: {
      type: Number,
      required: [true, 'Product price is required'],
      min: [0, 'Price cannot be negative'],
    },
  },
  {
    // Mongoose automatically adds createdAt and updatedAt
    timestamps: true,
  }
);

const Product = mongoose.model('Product', productSchema);

module.exports = Product;
