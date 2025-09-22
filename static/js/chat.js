document.addEventListener('DOMContentLoaded', () => {
    const socket = io();
    let activeContact = null;

    // --- DOM элементы ---
    const contactList = document.querySelector('.contact-list');
    const chatWithUsername = document.getElementById('chat-with-username');
    const chatWithStatus = document.getElementById('chat-with-status');
    const messagesArea = document.getElementById('messages-area');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const cryptoKeyInput = document.getElementById('crypto-key');

    // --- Шифрование ---
    // Функция для шифрования текста
    function encrypt(text, key) {
        if (!key) return text; // Если ключа нет, не шифруем
        let result = [];
        for (let i = 0; i < text.length; i++) {
            const textCharCode = text.charCodeAt(i);
            const keyCharCode = key.charCodeAt(i % key.length);
            result.push(textCharCode + keyCharCode);
        }
        // Преобразуем массив чисел в строку и кодируем в Base64
        return btoa(JSON.stringify(result));
    }

    // Функция для расшифровки текста
    function decrypt(encryptedText, key) {
        if (!key) return encryptedText;
        try {
            // Декодируем из Base64 и парсим JSON
            const charCodes = JSON.parse(atob(encryptedText));
            let result = '';
            for (let i = 0; i < charCodes.length; i++) {
                const keyCharCode = key.charCodeAt(i % key.length);
                result += String.fromCharCode(charCodes[i] - keyCharCode);
            }
            return result;
        } catch (e) {
            // Если ключ неверный, atob или JSON.parse выдадут ошибку
            // или результат будет бессмыслицей.
            console.error("Decryption failed:", e);
            return encryptedText; // Возвращаем исходный шифротекст
        }
    }

    // --- Функции чата ---
    function addMessageToUI(sender, content, timestamp, isSent) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', isSent ? 'sent' : 'received');
        
        const key = cryptoKeyInput.value;
        const decryptedContent = decrypt(content, key);

        messageDiv.innerHTML = `
            <p>${decryptedContent.replace(/\n/g, '<br>')}</p>
            <span class="timestamp">${timestamp}</span>
        `;
        messagesArea.appendChild(messageDiv);
        messagesArea.scrollTop = messagesArea.scrollHeight;
    }

    function selectContact(contactElement) {
        // Снимаем выделение с предыдущего контакта
        const currentActive = document.querySelector('.contact.active');
        if (currentActive) {
            currentActive.classList.remove('active');
        }

        // Выделяем новый
        contactElement.classList.add('active');
        activeContact = contactElement.dataset.username;

        // Обновляем заголовок чата
        chatWithUsername.textContent = `Чат с ${activeContact}`;
        // TODO: Запросить актуальный статус
        chatWithStatus.textContent = ''; 

        // Очищаем чат и запрашиваем историю
        messagesArea.innerHTML = '';
        socket.emit('get_chat_history', { contact: activeContact });
    }

    // --- Обработчики событий ---
    contactList.addEventListener('click', (e) => {
        const contact = e.target.closest('.contact');
        if (contact) {
            selectContact(contact);
        }
    });

    sendButton.addEventListener('click', () => {
        const messageText = messageInput.value.trim();
        const key = cryptoKeyInput.value;

        if (messageText && activeContact) {
            if (!key) {
                alert('Пожалуйста, введите ключ-пароль для шифрования!');
                return;
            }
            const encryptedMessage = encrypt(messageText, key);
            socket.emit('send_message', {
                recipient: activeContact,
                content: encryptedMessage
            });
            messageInput.value = '';
        }
    });
    
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendButton.click();
        }
    });

    // --- События Socket.IO ---
    socket.on('connect', () => {
        console.log('Connected to server!');
    });

    socket.on('new_message', (data) => {
        // Отображаем сообщение, только если открыт чат с этим пользователем
        const chatPartner = (data.sender === currentUsername) ? data.recipient : data.sender;
        if (chatPartner === activeContact) {
            const isSent = data.sender === currentUsername;
            addMessageToUI(data.sender, data.content, data.timestamp, isSent);
        }
    });

    socket.on('chat_history', (data) => {
        if (data.contact === activeContact) {
            messagesArea.innerHTML = '';
            data.history.forEach(msg => {
                const isSent = msg.sender === currentUsername;
                addMessageToUI(msg.sender, msg.content, msg.timestamp, isSent);
            });
        }
    });
    
    socket.on('status_update', (data) => {
        const statusIndicator = document.getElementById(`status-${data.username}`);
        if (statusIndicator) {
            statusIndicator.className = 'status-indicator ' + (data.is_online ? 'online' : 'offline');
        }
        if (data.username === activeContact) {
            chatWithStatus.textContent = data.is_online ? 'в сети' : `был(а) в сети ${data.last_seen}`;
        }
    });
});
