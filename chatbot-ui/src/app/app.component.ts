import { Component, OnInit } from '@angular/core';


const DEFAULT_ACCOUNT_IDS = ["account_id_1", "account_id_2"];
const STORAGE_KEY = 'availableAccountIds';
const SESSION_ACCOUNT_KEY = 'sessionAccountId';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css']
})
export class AppComponent implements OnInit {
  selectedAccountId: string | null = null;


  ngOnInit() {
    this.initializeAccount();
  }

  private initializeAccount() {
    this.selectedAccountId = sessionStorage.getItem(SESSION_ACCOUNT_KEY);
    if (this.selectedAccountId) return;

    const stored = localStorage.getItem(STORAGE_KEY);
    let availableAccounts = stored ? JSON.parse(stored) : [...DEFAULT_ACCOUNT_IDS];

    if (availableAccounts.length === 0) {
      availableAccounts = [...DEFAULT_ACCOUNT_IDS];
    }

    const accountId = availableAccounts.pop();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(availableAccounts));
    sessionStorage.setItem(SESSION_ACCOUNT_KEY, accountId);
    this.selectedAccountId = accountId;
  }
}