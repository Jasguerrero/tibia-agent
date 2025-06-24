import os
from dotenv import load_dotenv
from agent.src.agent import TibiaAgent
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv('./agent/.env', override=True)

# Initialize FastAPI app
app = FastAPI(title="Tibia Agent API", description="AI assistant for Tibia house auctions and loot splitting")

# Global instances
agent: Optional[TibiaAgent] = None
mongo_client: Optional[AsyncIOMotorClient] = None
database = None

# Pydantic models
class QuestionRequest(BaseModel):
    question: str

class QuestionResponse(BaseModel):
    response: str

async def init_mongodb():
    """Initialize MongoDB connection"""
    global mongo_client, database
    
    mongo_host = os.getenv("MONGO_HOST", "localhost")
    mongo_port = int(os.getenv("MONGO_PORT", "27017"))
    mongo_db = os.getenv("MONGO_DB", "tibia_agent")
    mongo_username = os.getenv("MONGO_USERNAME")
    mongo_password = os.getenv("MONGO_PASSWORD")
    
    try:
        # Build connection string
        if mongo_username and mongo_password:
            connection_string = f"mongodb://{mongo_username}:{mongo_password}@{mongo_host}:{mongo_port}/{mongo_db}"
        else:
            connection_string = f"mongodb://{mongo_host}:{mongo_port}/{mongo_db}"
        
        mongo_client = AsyncIOMotorClient(connection_string)
        database = mongo_client[mongo_db]
        
        # Test the connection
        await mongo_client.admin.command('ping')
        logger.info(f"✅ Connected to MongoDB at {mongo_host}:{mongo_port}")
        
        return database
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {str(e)}")
        raise RuntimeError(f"MongoDB connection failed: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """Initialize the agent and MongoDB on startup"""
    global agent
    
    # Initialize MongoDB
    db = await init_mongodb()
    
    # Initialize Tibia Agent
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("❌ Error: ANTHROPIC_API_KEY not found in environment variables")
        raise RuntimeError("ANTHROPIC_API_KEY not found")
    
    agent = TibiaAgent(api_key, database=db)
    logger.info("✅ Tibia Agent initialized successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up connections on shutdown"""
    global mongo_client
    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB connection closed")

@app.post("/ask", response_model=QuestionResponse)
async def ask_question(request: QuestionRequest):
    """Ask a question to the Tibia Agent"""
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        logger.info(f"Received question: {request.question}")
        
        # Collect all updates and return only the final result
        final_response = ""
        async for update in agent.chat(request.question):
            if isinstance(update, dict):
                if update["type"] == "progress":
                    logger.info(f"Progress: {update['content']}")
                elif update["type"] == "result":
                    final_response = update["content"]
                    logger.info(f"Final response generated")
            else:
                logger.info(f"Update: {str(update)}")
        
        if not final_response:
            final_response = "I'm here to help you with Tibia house auctions and loot splitting! Just ask me about houses in any world and town."
        
        return QuestionResponse(response=final_response)
    
    except Exception as e:
        logger.error(f"Error processing question: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing question: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy"
    }

if __name__ == "__main__":
    logger.info("🚀 Starting Tibia Agent API server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
