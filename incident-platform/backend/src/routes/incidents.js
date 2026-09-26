import { Router } from "express";
import * as controller from "../controllers/incidents.js";
const router = Router();
router.get("/", controller.list);
router.post("/", controller.create);
router.get("/:id", controller.get);
router.patch("/:id/analysis", controller.analysis);
router.patch("/:id/status", controller.status);
export default router;
