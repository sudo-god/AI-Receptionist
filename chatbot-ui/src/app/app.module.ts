import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { NbGlobalPhysicalPosition, NbLayoutModule, NbThemeModule, NbToastrModule } from '@nebular/theme';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { HttpClientModule } from '@angular/common/http';
import { AppComponent } from './app.component';
import { ChatInterfaceModule } from './features/chat-interface/chat-interface.module';
import { AppRoutingModule } from './app.routes';
import { MatIconModule } from '@angular/material/icon';
import { MatToolbarModule } from '@angular/material/toolbar';
import { FileUploadModule } from './features/upload-file/upload-file.module';


@NgModule({
  declarations: [
    AppComponent,
  ],
  imports: [
    BrowserModule,
    BrowserAnimationsModule,
    NbThemeModule.forRoot({ name: 'corporate' }),
    NbLayoutModule,
    ChatInterfaceModule,
    AppRoutingModule,
    MatToolbarModule,
    MatIconModule,
    FileUploadModule,
    HttpClientModule,
    NbToastrModule.forRoot({
      position: NbGlobalPhysicalPosition.TOP_RIGHT, // Position of the toast
      duration: 3000, // Duration of the toast in milliseconds
      preventDuplicates: true
    }),
  ],
  // The bootstrap array specifies the root component(s) that Angular should 
  // bootstrap (initialize) when the application starts.
  // AppComponent is designated as the root component that will be loaded first.
  bootstrap: [AppComponent]
})

export class AppModule { }