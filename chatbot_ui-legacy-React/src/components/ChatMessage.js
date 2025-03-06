import React from 'react';
import '../style/ChatMessage.css';
import { marked } from 'marked';


function ChatMessage({ message, sender, is_interrupted }) {
    const className = sender === 'user' ? 'chat-message user' : 'chat-message bot';
    
    return (
        <div className={className}>
            <div className="message-content" style={{ backgroundColor: is_interrupted ? 'yellow' : '' }}>
                <div dangerouslySetInnerHTML={{ __html: marked(message) }} />
            </div>
        </div>
    );
}

export default ChatMessage;
