// backend/src/utils/db.js
// MongoDB connection using Mongoose
// Reads MONGO_URI from environment variables — credentials are NEVER hardcoded

const mongoose = require('mongoose');
const logger = require('./logger');

const MAX_RETRIES = 5;
const RETRY_DELAY_MS = 3000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const connectDB = async () => {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const conn = await mongoose.connect(process.env.MONGO_URI, {
        serverSelectionTimeoutMS: 10000, // 10 seconds per attempt
        // Mongoose 8 no longer needs useNewUrlParser / useUnifiedTopology options
      });

      logger.info(`MongoDB connected: ${conn.connection.host}`, {
        service: 'database',
      });
      return; // success — exit the retry loop
    } catch (error) {
      logger.error(`MongoDB connection failed (attempt ${attempt}/${MAX_RETRIES})`, {
        service: 'database',
        errorType: error.name,
        message: error.message,
        // NOTE: Do NOT log the connection string — it contains credentials
      });

      if (attempt < MAX_RETRIES) {
        logger.warn(`Retrying MongoDB connection in ${RETRY_DELAY_MS / 1000}s…`, { service: 'database' });
        await sleep(RETRY_DELAY_MS);
      } else {
        logger.error('All MongoDB connection attempts failed. Exiting.', { service: 'database' });
        process.exit(1);
      }
    }
  }
};

// Listen for disconnection events after initial connection
mongoose.connection.on('disconnected', () => {
  logger.warn('MongoDB disconnected', { service: 'database' });
});

mongoose.connection.on('reconnected', () => {
  logger.info('MongoDB reconnected', { service: 'database' });
});

module.exports = connectDB;
