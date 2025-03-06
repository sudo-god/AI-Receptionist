import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatContainerComponent } from './components/chat-container/chat-container.component';
import { ChatInputComponent } from './components/chat-input/chat-input.component';
import { ChatMessageComponent } from './components/chat-message/chat-message.component';
import { MatIconModule } from '@angular/material/icon';
import { FileUploadModule } from '../upload-file/upload-file.module';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';


@NgModule({
    imports: [
        CommonModule,
        FormsModule,
        MatIconModule,
        FileUploadModule,
        BrowserAnimationsModule
    ],
    declarations: [
        ChatContainerComponent,
        ChatInputComponent,
        ChatMessageComponent,
    ],
    exports: [
        ChatContainerComponent,
        ChatInputComponent,
        ChatMessageComponent
    ],
    bootstrap: [ChatContainerComponent]
})
export class ChatInterfaceModule { }
