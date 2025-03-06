import React from 'react';
import ChatMessage from './ChatMessage';
import '../style/ChatContainer.css';


function ChatContainer({ messages, status }) {
    return (
        <div className="chat-container">
        <div className="chat-header">Spaceo Chatbot</div>
        <div className="chat-messages">
            {messages.map((msg, idx) => (
            <ChatMessage
                key={idx}
                message={msg.text}
                sender={msg.sender}
                is_interrupted={msg.is_interrupted}
            />
            ))}
            {status === 'loading' ? 
                <ChatMessage
                    key={0}
                    message={"Processing your request..."}
                    sender={"bot"}
                /> : null
            }
        </div>
        </div>
    );
}


export default ChatContainer;
