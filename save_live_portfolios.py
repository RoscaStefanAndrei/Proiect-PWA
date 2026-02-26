import django, os, sys, datetime
os.environ['DJANGO_SETTINGS_MODULE']='finance_project.settings'
django.setup()

sys.path.append('c:\\Licenta\\Proiect-PWA')
from django.contrib.auth.models import User
from SmartVest.models import SavedPortfolio
from selection_algorithm import run_full_pipeline

def main():
    try:
        user = User.objects.get(username='StefanRoscaSuperUser')
    except User.DoesNotExist:
        print('User StefanRoscaSuperUser not found. Check the database.')
        return

    today = datetime.date.today()
    print(f'Running live selection algorithm for {today}...')

    profiles = ['conservative', 'balanced', 'aggressive']
    budget = 10000.0

    for profile in profiles:
        print(f"\n--- Running profile: {profile} ---")
        try:
            result = run_full_pipeline(profile_type=profile, budget=budget)
            
            if result and result.get('success'):
                df_plan = result.get('plan_investitii')
                portfolio_data = []
                
                if df_plan is not None and not df_plan.empty:
                    for index, row in df_plan.iterrows():
                        try:
                            weight_str = str(row['Pondere']).replace('%', '') if isinstance(row['Pondere'], str) else str(row['Pondere'])
                            price_str = str(row['Price']).replace('$', '') if isinstance(row['Price'], str) else str(row['Price'])
                            val_str = str(row.get('Valoare_Investitie ($)', 0)).replace('$', '') if isinstance(row.get('Valoare_Investitie ($)', 0), str) else str(row.get('Valoare_Investitie ($)', 0))
                            
                            portfolio_data.append({
                                'Simbol': row['Ticker'],
                                'Companie': row['Ticker'],
                                'Sector': 'N/A',
                                'Industrie': 'N/A',
                                'Alocare': str(weight_str),
                                'Pret_Curent': float(price_str),
                                'Actiuni': float(row.get('Nr_Actiuni', 0)),
                                'Valoare': float(val_str)
                            })
                        except Exception as parse_e:
                            print(f"Error parsing row {row['Ticker']}: {parse_e}")
                            
                name = f"{profile}-1"
                
                if portfolio_data:
                    SavedPortfolio.objects.filter(user=user, name=name).delete()
                    SavedPortfolio.objects.create(
                        user=user,
                        name=name,
                        description=f'Shadow test portfolio generated using live algorithm on {today}.',
                        portfolio_data=portfolio_data
                    )
                    print(f"✅ Saved portfolio '{name}' with {len(portfolio_data)} stocks.")
                else:
                    print(f"❌ Pipeline finished but returned empty portfolio data for {profile}.")
            else:
                err = result.get('error', 'Unknown pipeline failure') if result else 'Returned None'
                print(f"❌ Pipeline failed for {profile}: {err}")
                
        except Exception as e:
            print(f"❌ CRITICAL ERROR running {profile}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    main()
