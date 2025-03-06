import React, { useState, useEffect, useRef } from 'react';
import ChatContainer from './components/ChatContainer';
import ChatInput from './components/ChatInput';
import './App.css';
import { v4 as uuidv4 } from 'uuid';


const DEFAULT_ACCOUNT_IDS = ["account_id_1", "account_id_2"];
const STORAGE_KEY = 'availableAccountIds';
const SESSION_ACCOUNT_KEY = 'sessionAccountId';



function App() {
  const [messages, setMessages] = useState([
    // Example: { sender: 'bot', text: 'Hello! Ask me anything.' }
  ]);
  const [status, setStatus] = useState('idle');
  const hasInitialized = useRef(false);
  const [selectedAccountId, setSelectedAccountId] = useState(() => {
    // Check if we already have an account for this session
    return sessionStorage.getItem(SESSION_ACCOUNT_KEY);
  });


  useEffect(() => {
    if (hasInitialized.current || selectedAccountId) return;
    hasInitialized.current = true;

    // Get available accounts from localStorage or initialize if empty
    const stored = localStorage.getItem(STORAGE_KEY);
    let availableAccounts = stored ? JSON.parse(stored) : [...DEFAULT_ACCOUNT_IDS];
    console.log("AVAILABLE ACCOUNT ID's:", availableAccounts)

    // If no accounts available, reset the pool
    if (availableAccounts.length === 0) {
      availableAccounts = [...DEFAULT_ACCOUNT_IDS];
    }

    // Select random account and remove it from pool
    const accountId = availableAccounts.pop();

    // Update localStorage and state
    localStorage.setItem(STORAGE_KEY, JSON.stringify(availableAccounts));
    sessionStorage.setItem(SESSION_ACCOUNT_KEY, accountId);
    console.log("ACCOUNT ID", accountId);

    setSelectedAccountId(accountId);
  }, [selectedAccountId]);

  // let accountId = sessionStorage.getItem('chatAccountId');
  // console.log("AVAILABLE ACCOUNT ID's:", availableAccountIds)

  // console.log("ACCOUNT ID FROM SESSION STORAGE:", accountId)
  // if (!accountId) {
  //   accountId = availableAccountIds.pop();
  //   sessionStorage.setItem('chatAccountId', accountId);
  // }

  // if (!accountId) {
  //   const newId = uuidv4();
  //   sessionStorage.setItem('chatAccountId', newId);
  // }

  const handleSend = async (message) => {
    // Add the user message to the local state
    setMessages((prev) => [...prev, { sender: 'user', text: message }]);
    setStatus('loading');
    // Call the Django backend
    try {
      const response = await fetch('http://localhost:8000/chat/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message, account_id: selectedAccountId }),
      });
      console.log("RESPONSE", response)
      
      const data = await response.json();
      setStatus('idle');

      if (response.ok) {
        // "data.response" should contain the bot's response
        setMessages((prev) => [...prev, { sender: 'bot', text: data.response , is_interrupted: data.is_interrupted }]);
      } else {
        // handle error
        setMessages((prev) => [...prev, { sender: 'bot', text: data.error || 'Error' }]);
      }
    } catch (error) {
      // handle network error
      setMessages((prev) => [...prev, { sender: 'bot', text: error.message }]);
      console.log("ERROR", error)
    }
  };

  return (
    <div className="app-container">
      <ChatContainer messages={messages} status={status}/>
      <ChatInput onSend={handleSend} />
    </div>
  );
}

export default App;
