import { Message } from '../../../../core/models/message';
import { Component, ElementRef, ViewChild, AfterViewInit } from '@angular/core';


@Component({
  selector: 'app-chat-container',
  templateUrl: './chat-container.component.html',
  styleUrls: ['./chat-container.component.css'],
})
export class ChatContainerComponent {
  messages: Message[] = [];
  status: string = 'idle'; // Receive status as input
  shouldScroll = false;
  @ViewChild('chatMessagesContainer') private chatMessagesContainer!: ElementRef;

  ngAfterViewInit() {
    console.log("ngAfterViewInit");
    setTimeout(() => {
      this.scrollToBottom();
    }, 0);
  }

  ngAfterViewChecked() {
    if (this.shouldScroll) {
      this.scrollToBottom();
      this.shouldScroll = false; // Reset the flag to avoid repeated scrolling
    }
  }

  scrollToBottom(): void {
    try {
      console.log("scrollHeight:", this.chatMessagesContainer.nativeElement.scrollHeight);
      console.log("window.document.body.scrollHeight:", window.document.body.scrollHeight);
      window.scrollTo({ top: window.document.body.scrollHeight, behavior: 'smooth' });
    } catch (err) {
      console.error('Error scrolling to bottom:', err);
    }
  }

  addMessage(message: Message): void {
    if (message.text != '') {
      this.messages.push(message);
      this.shouldScroll = true;
    }
  }

  updateStatus(newStatus: string): void {
    console.log('newStatus', newStatus);
    this.status = newStatus;
  }
}