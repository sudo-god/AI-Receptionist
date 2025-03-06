import { Component, Input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { marked } from 'marked';
import { Message } from '../../../../core/models/message';

@Component({
  selector: 'app-chat-message',
  templateUrl: './chat-message.component.html',
  styleUrls: ['./chat-message.component.css'],
})
export class ChatMessageComponent {
  @Input() message: Message = { text: '', sender: '', is_interrupted: false };
  private markedMessage: string = '';

  async ngOnChanges() {
    const parsed = await marked(this.message.text || '');
    this.markedMessage = parsed;
  }

  get sanitizedMessage(): SafeHtml { 
    return this.sanitizer.bypassSecurityTrustHtml(this.markedMessage);
  }

  constructor(private sanitizer: DomSanitizer) {}
}