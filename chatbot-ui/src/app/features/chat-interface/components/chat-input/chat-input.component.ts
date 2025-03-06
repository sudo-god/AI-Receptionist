import { HttpClient } from '@angular/common/http';
import { Component, Output, EventEmitter, Input } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { Message } from '../../../../core/models/message';
import { environment } from '../../../../../environments/environment';

const SESSION_ACCOUNT_KEY = 'sessionAccountId';

@Component({
  selector: 'app-chat-input',
  templateUrl: './chat-input.component.html',
  styleUrls: ['./chat-input.component.css'],
})
export class ChatInputComponent {
  messageText: string = '';
  status: string = 'idle';
  @Output() emitMessage = new EventEmitter<Message>();
  @Output() emitStatus = new EventEmitter<string>();

  selectedAccountId: string | null = null;

  ngOnInit() {
    this.selectedAccountId = sessionStorage.getItem(SESSION_ACCOUNT_KEY);
  }

  constructor(private http: HttpClient) {}

  async handleSend(messageText: string) {
    if (messageText === '') {
      return;
    }
    this.emitMessage.emit({ text: messageText, sender: 'user', is_interrupted: false });
    this.emitStatus.emit('loading')
    try {
      this.http.post<any>(`${environment.apiUrl}/chat/`, { message: messageText, account_id: this.selectedAccountId }).subscribe(response => {
        if (response.response === null || response.response === "") {
          this.emitMessage.emit({ text: 'Sorry, I couldn\'t understand your request. Please try again. null or empty response received from server.', sender: 'bot', is_interrupted: false });
          this.emitStatus.emit('idle')
        } else {
          this.emitMessage.emit({ text: response.response, sender: 'bot', is_interrupted: response.is_interrupted });
          this.emitStatus.emit('idle')
        }
      });
    } catch (error) {
      this.emitMessage.emit({ text: (error as any).message, sender: 'bot', is_interrupted: false });
      this.emitStatus.emit('idle')
    }
    
    this.messageText = '';
  }
}
