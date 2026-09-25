// backend/src/controllers/productController.js
// Controller layer: handles HTTP request/response and delegates to service
// All errors are passed to next(error) → caught by errorMiddleware

const productService = require('../services/productService');
const logger = require('../utils/logger');
const mongoose = require('mongoose');

/**
 * Helper: Validate a MongoDB ObjectId format.
 * Returns false if the id string is not a valid ObjectId.
 */
const isValidObjectId = (id) => mongoose.Types.ObjectId.isValid(id);

// ─── GET /api/products ────────────────────────────────────────────────────────
const getAllProducts = async (req, res, next) => {
  try {
    const products = await productService.getAllProducts();

    logger.info('Products fetched successfully', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 200,
    });

    res.status(200).json({
      success: true,
      count: products.length,
      data: products,
    });
  } catch (error) {
    logger.error('Failed to fetch products', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 500,
      errorType: error.name,
      message: error.message,
    });
    next(error);
  }
};

// ─── GET /api/products/:id ────────────────────────────────────────────────────
const getProductById = async (req, res, next) => {
  try {
    const { id } = req.params;

    // Validate ObjectId format before hitting the database
    if (!isValidObjectId(id)) {
      logger.warn('Invalid product ID format', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 400,
        errorType: 'InvalidObjectId',
        message: `"${id}" is not a valid MongoDB ObjectId`,
      });
      return res.status(400).json({
        success: false,
        error: 'Invalid product ID format',
      });
    }

    const product = await productService.getProductById(id);

    if (!product) {
      logger.warn('Product not found', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 404,
        errorType: 'NotFound',
        message: `Product with id ${id} not found`,
      });
      return res.status(404).json({
        success: false,
        error: 'Product not found',
      });
    }

    logger.info('Product fetched successfully', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 200,
    });

    res.status(200).json({ success: true, data: product });
  } catch (error) {
    logger.error('Failed to fetch product by ID', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 500,
      errorType: error.name,
      message: error.message,
    });
    next(error);
  }
};

// ─── POST /api/products ───────────────────────────────────────────────────────
const createProduct = async (req, res, next) => {
  try {
    const { name, price } = req.body;

    // Basic presence validation before hitting Mongoose
    if (name === undefined || price === undefined) {
      logger.warn('Missing required fields for product creation', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 400,
        errorType: 'ValidationError',
        message: 'name and price are required fields',
      });
      return res.status(400).json({
        success: false,
        error: 'name and price are required fields',
      });
    }

    const product = await productService.createProduct({ name, price });

    logger.info('Product created successfully', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 201,
    });

    res.status(201).json({ success: true, data: product });
  } catch (error) {
    // Mongoose validation error (e.g., price < 0, name empty)
    if (error.name === 'ValidationError') {
      const messages = Object.values(error.errors).map((e) => e.message);
      logger.warn('Product validation failed', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 422,
        errorType: 'ValidationError',
        message: messages.join(', '),
      });
      return res.status(422).json({
        success: false,
        error: 'Validation failed',
        details: messages,
      });
    }

    logger.error('Failed to create product', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 500,
      errorType: error.name,
      message: error.message,
    });
    next(error);
  }
};

// ─── PUT /api/products/:id ────────────────────────────────────────────────────
const updateProduct = async (req, res, next) => {
  try {
    const { id } = req.params;

    if (!isValidObjectId(id)) {
      logger.warn('Invalid product ID format for update', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 400,
        errorType: 'InvalidObjectId',
        message: `"${id}" is not a valid MongoDB ObjectId`,
      });
      return res.status(400).json({
        success: false,
        error: 'Invalid product ID format',
      });
    }

    const product = await productService.updateProduct(id, req.body);

    if (!product) {
      logger.warn('Product not found for update', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 404,
        errorType: 'NotFound',
        message: `Product with id ${id} not found`,
      });
      return res.status(404).json({
        success: false,
        error: 'Product not found',
      });
    }

    logger.info('Product updated successfully', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 200,
    });

    res.status(200).json({ success: true, data: product });
  } catch (error) {
    if (error.name === 'ValidationError') {
      const messages = Object.values(error.errors).map((e) => e.message);
      logger.warn('Product validation failed on update', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 422,
        errorType: 'ValidationError',
        message: messages.join(', '),
      });
      return res.status(422).json({
        success: false,
        error: 'Validation failed',
        details: messages,
      });
    }

    logger.error('Failed to update product', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 500,
      errorType: error.name,
      message: error.message,
    });
    next(error);
  }
};

// ─── DELETE /api/products/:id ─────────────────────────────────────────────────
const deleteProduct = async (req, res, next) => {
  try {
    const { id } = req.params;

    if (!isValidObjectId(id)) {
      logger.warn('Invalid product ID format for delete', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 400,
        errorType: 'InvalidObjectId',
        message: `"${id}" is not a valid MongoDB ObjectId`,
      });
      return res.status(400).json({
        success: false,
        error: 'Invalid product ID format',
      });
    }

    const product = await productService.deleteProduct(id);

    if (!product) {
      logger.warn('Product not found for delete', {
        method: req.method,
        endpoint: req.originalUrl,
        statusCode: 404,
        errorType: 'NotFound',
        message: `Product with id ${id} not found`,
      });
      return res.status(404).json({
        success: false,
        error: 'Product not found',
      });
    }

    logger.info('Product deleted successfully', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 200,
    });

    res.status(200).json({
      success: true,
      message: 'Product deleted successfully',
    });
  } catch (error) {
    logger.error('Failed to delete product', {
      method: req.method,
      endpoint: req.originalUrl,
      statusCode: 500,
      errorType: error.name,
      message: error.message,
    });
    next(error);
  }
};

module.exports = {
  getAllProducts,
  getProductById,
  createProduct,
  updateProduct,
  deleteProduct,
};
