import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { ChatContainerComponent } from './features/chat-interface/components/chat-container/chat-container.component';

export const routes: Routes = [
    {
        title: 'Home',
        path: '',
        redirectTo: 'chat',
        pathMatch: 'full'
    },
    {
        title: "Dixit's AI Chatbot",
        path: 'chat',
        component: ChatContainerComponent
    }
];

@NgModule({
    imports: [RouterModule.forRoot(routes)],
    exports: [RouterModule]
  })
export class AppRoutingModule { }
