import mongoose from "mongoose";
import { Incident } from "../models/Incident.js";
export async function connectDatabase(uri) {
  if (!uri) throw new Error("MONGODB_URI is required");
  await mongoose.connect(uri, {
    serverSelectionTimeoutMS: 5000,
    connectTimeoutMS: 5000,
    socketTimeoutMS: 10000,
  });
  await Incident.init(); // Wait for the unique index before accepting writes.
}
export async function databaseHealthy() {
  if (mongoose.connection.readyState !== 1) return false;
  try {
    await mongoose.connection.db.command({ ping: 1 }, { timeoutMS: 2000 });
    return true;
  } catch {
    return false;
  }
}
