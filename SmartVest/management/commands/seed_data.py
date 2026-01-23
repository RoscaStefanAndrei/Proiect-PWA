import random
import requests
from faker import Faker
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from SmartVest.models import UserProfile, SavedPortfolio

class Command(BaseCommand):
    help = 'Seeds the database with mock users and portfolios'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding data...')
        fake = Faker()
        
        # Real tickers to ensure valid data for tracking
        TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'BRK-B', 'V', 'JNJ', 'WMT', 'JPM', 'PG', 'MA', 'UNH', 'DIS', 'HD', 'VZ', 'KO', 'PEP']
        
        for i in range(20):
            # 1. Create User
            username = fake.unique.user_name()
            email = fake.unique.email()
            password = 'password123'
            
            user = User.objects.create_user(username=username, email=email, password=password)
            self.stdout.write(f'Created user: {username}')
            
            # 2. Create Profile & Avatar
            # DiceBear API for consistent avatars
            avatar_url = f"https://api.dicebear.com/7.x/avataaars/png?seed={username}"
            try:
                response = requests.get(avatar_url, timeout=10)
                if response.status_code == 200:
                    profile, created = UserProfile.objects.get_or_create(user=user)
                    profile.avatar.save(f"{username}_avatar.png", ContentFile(response.content), save=True)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Could not fetch avatar for {username}: {e}"))

            # 3. Create Portfolios
            num_portfolios = random.randint(1, 3)
            for j in range(num_portfolios):
                portfolio_name = f"{random.choice(['Conservative', 'Balanced', 'Aggressive', 'Tech', 'Growth'])} {fake.word().capitalize()}"
                
                # Generate Portfolio Data
                portfolio_data = []
                num_stocks = random.randint(3, 8)
                selected_tickers = random.sample(TICKERS, num_stocks)
                
                total_investment = random.randint(5000, 50000)
                remaining_weight = 100
                
                for k, ticker in enumerate(selected_tickers):
                    # Distribute weights roughly
                    if k == num_stocks - 1:
                        weight = remaining_weight
                    else:
                        weight = random.randint(5, remaining_weight - (num_stocks - k) * 5)
                        remaining_weight -= weight
                    
                    # Random price roughly around 50-500
                    price = round(random.uniform(50, 500), 2)
                    
                    # Calculate investment for this stock
                    invest_val = (weight / 100) * total_investment
                    num_shares = invest_val / price
                    
                    portfolio_data.append({
                        'Ticker': ticker,
                        'Pondere': f"{weight}%",
                        'Price': f"${price}",
                        'Valoare_Investitie_USD': f"${invest_val:,.2f}",
                        'Nr_Actiuni': f"{num_shares:,.2f}"
                    })
                
                SavedPortfolio.objects.create(
                    user=user,
                    name=portfolio_name,
                    description=fake.sentence(),
                    portfolio_data=portfolio_data
                )
        
        self.stdout.write(self.style.SUCCESS('Successfully seeded 20 users with portfolios!'))
