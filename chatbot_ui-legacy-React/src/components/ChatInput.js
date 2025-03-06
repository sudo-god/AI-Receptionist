import React, { useState } from 'react';
import '../style/ChatInput.css';

function ChatInput({ onSend }) {
  const [inputValue, setInputValue] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (inputValue.trim()) {
      onSend(inputValue);
      setInputValue('');
    }
  };

  return (
    <div className="chat-input-container">
      <form onSubmit={handleSubmit} className="chat-input-form">
        <input
          type="text"
          placeholder="Type your message..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          className="chat-input-field"
        />
        <button type="submit" className="chat-input-send">
          Send
        </button>
      </form>
    </div>
  );
}

export default ChatInput;
