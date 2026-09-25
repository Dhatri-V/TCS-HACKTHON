// backend/src/services/productService.js
// Service layer: all database logic lives here, not in routes or controllers

const Product = require('../models/Product');

/**
 * Retrieve all products from the database.
 * @returns {Promise<Product[]>}
 */
const getAllProducts = async () => {
  return await Product.find().sort({ createdAt: -1 });
};

/**
 * Retrieve a single product by its MongoDB ObjectId.
 * Returns null if not found (controller handles the 404 response).
 * @param {string} id - MongoDB ObjectId string
 * @returns {Promise<Product|null>}
 */
const getProductById = async (id) => {
  return await Product.findById(id);
};

/**
 * Create a new product.
 * @param {object} data - { name, price }
 * @returns {Promise<Product>}
 */
const createProduct = async (data) => {
  const product = new Product(data);
  return await product.save();
};

/**
 * Update an existing product by id.
 * Returns null if not found.
 * @param {string} id
 * @param {object} data - fields to update
 * @returns {Promise<Product|null>}
 */
const updateProduct = async (id, data) => {
  return await Product.findByIdAndUpdate(
    id,
    data,
    {
      new: true,          // return the updated document
      runValidators: true, // apply schema validators on update
    }
  );
};

/**
 * Delete a product by id.
 * Returns null if not found.
 * @param {string} id
 * @returns {Promise<Product|null>}
 */
const deleteProduct = async (id) => {
  return await Product.findByIdAndDelete(id);
};

module.exports = {
  getAllProducts,
  getProductById,
  createProduct,
  updateProduct,
  deleteProduct,
};
